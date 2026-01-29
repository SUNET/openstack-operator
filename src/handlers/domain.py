"""Kopf handlers for OpenstackDomain CRD."""

import logging
from typing import Any

import kopf

from openstack_client import OpenStackClient
from resources.domain import delete_domain, ensure_domain, get_domain_info
from resources.registry import ResourceRegistry
from utils import now_iso

logger = logging.getLogger(__name__)

# Module-level registry and client (initialized lazily)
_registry: ResourceRegistry | None = None
_os_client: OpenStackClient | None = None


def get_registry() -> ResourceRegistry:
    """Get or create the resource registry."""
    global _registry
    if _registry is None:
        _registry = ResourceRegistry()
    return _registry


def get_openstack_client() -> OpenStackClient:
    """Get or create the OpenStack client."""
    global _os_client
    if _os_client is None:
        _os_client = OpenStackClient()
    return _os_client


def _set_patch_condition(
    patch: kopf.Patch,
    condition_type: str,
    condition_status: str,
    reason: str = "",
    message: str = "",
) -> None:
    """Set or update a condition in patch.status.conditions."""
    if "conditions" not in patch.status:
        patch.status["conditions"] = []

    conditions: list[dict[str, str]] = patch.status["conditions"]

    for condition in conditions:
        if condition["type"] == condition_type:
            if condition["status"] != condition_status:
                condition["status"] = condition_status
                condition["lastTransitionTime"] = now_iso()
            condition["reason"] = reason
            condition["message"] = message
            return

    conditions.append(
        {
            "type": condition_type,
            "status": condition_status,
            "reason": reason,
            "message": message,
            "lastTransitionTime": now_iso(),
        }
    )


@kopf.on.create("sunet.se", "v1alpha1", "openstackdomains")
def create_domain_handler(
    spec: dict[str, Any],
    patch: kopf.Patch,
    name: str,
    **_: Any,
) -> None:
    """Handle OpenstackDomain creation."""
    logger.info(f"Creating OpenstackDomain: {name}")

    patch.status["phase"] = "Provisioning"
    patch.status["conditions"] = []

    client = get_openstack_client()
    registry = get_registry()

    try:
        domain_name = spec["name"]
        description = spec.get("description", "")
        enabled = spec.get("enabled", True)

        _set_patch_condition(patch, "DomainReady", "False", "Creating", "")

        domain_id = ensure_domain(client, domain_name, description, enabled)

        # Register in ConfigMap
        registry.register("domains", domain_name, domain_id, cr_name=name)

        patch.status["domainId"] = domain_id
        _set_patch_condition(patch, "DomainReady", "True", "Created", "")
        patch.status["phase"] = "Ready"
        patch.status["lastSyncTime"] = now_iso()

        logger.info(f"Successfully created OpenstackDomain: {name} (id={domain_id})")

    except Exception as e:
        logger.error(f"Failed to create OpenstackDomain {name}: {e}")
        patch.status["phase"] = "Error"
        _set_patch_condition(patch, "DomainReady", "False", "Error", str(e)[:200])
        raise kopf.TemporaryError(f"Creation failed: {e}", delay=60)


@kopf.on.update("sunet.se", "v1alpha1", "openstackdomains")
def update_domain_handler(
    spec: dict[str, Any],
    status: dict[str, Any],
    patch: kopf.Patch,
    name: str,
    **_: Any,
) -> None:
    """Handle OpenstackDomain updates."""
    logger.info(f"Updating OpenstackDomain: {name}")

    client = get_openstack_client()
    patch.status["phase"] = "Provisioning"

    # Preserve existing status fields
    for key in ("domainId", "conditions"):
        if key in status and key not in patch.status:
            patch.status[key] = status[key]

    try:
        domain_name = spec["name"]
        description = spec.get("description", "")
        enabled = spec.get("enabled", True)
        domain_id = status.get("domainId")

        if not domain_id:
            # No domain ID, treat as create
            create_domain_handler(spec=spec, patch=patch, name=name)
            return

        # Update existing domain
        client.update_domain(domain_id, description=description, enabled=enabled)

        _set_patch_condition(patch, "DomainReady", "True", "Updated", "")
        patch.status["phase"] = "Ready"
        patch.status["lastSyncTime"] = now_iso()

        logger.info(f"Successfully updated OpenstackDomain: {name}")

    except Exception as e:
        logger.error(f"Failed to update OpenstackDomain {name}: {e}")
        patch.status["phase"] = "Error"
        _set_patch_condition(patch, "DomainReady", "False", "Error", str(e)[:200])
        raise kopf.TemporaryError(f"Update failed: {e}", delay=60)


@kopf.on.delete("sunet.se", "v1alpha1", "openstackdomains")
def delete_domain_handler(
    spec: dict[str, Any],
    status: dict[str, Any],
    name: str,
    **_: Any,
) -> None:
    """Handle OpenstackDomain deletion."""
    logger.info(f"Deleting OpenstackDomain: {name}")

    client = get_openstack_client()
    registry = get_registry()

    domain_name = spec["name"]
    domain_id = status.get("domainId")

    if not domain_id:
        logger.warning(f"No domainId in status for {name}, nothing to delete")
        return

    try:
        delete_domain(client, domain_id)
        registry.unregister("domains", domain_name)
        logger.info(f"Successfully deleted OpenstackDomain: {name}")

    except Exception as e:
        logger.error(f"Failed to delete OpenstackDomain {name}: {e}")
        raise kopf.TemporaryError(f"Deletion failed: {e}", delay=60)


@kopf.timer("sunet.se", "v1alpha1", "openstackdomains", interval=300)
def reconcile_domain(
    spec: dict[str, Any],
    status: dict[str, Any],
    patch: kopf.Patch,
    name: str,
    **_: Any,
) -> None:
    """Periodic reconciliation to detect and repair drift."""
    if status.get("phase") != "Ready":
        return

    logger.debug(f"Reconciling OpenstackDomain: {name}")

    client = get_openstack_client()
    domain_name = spec["name"]

    try:
        info = get_domain_info(client, domain_name)
        if not info:
            logger.warning(f"Domain {domain_name} not found, triggering recreate")
            patch.status["phase"] = "Pending"
            patch.status["domainId"] = None
            return

        if info["domain_id"] != status.get("domainId"):
            logger.warning(f"Domain ID mismatch for {domain_name}")
            patch.status["phase"] = "Pending"
            patch.status["domainId"] = info["domain_id"]
            return

        patch.status["lastSyncTime"] = now_iso()

    except Exception as e:
        logger.error(f"Reconciliation failed for {name}: {e}")
