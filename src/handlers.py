"""Kopf handlers for OpenstackProject CRD."""

import logging
import os
import sys
from pathlib import Path
from typing import Any

# Add src directory to path for imports when run as script by Kopf
_src_dir = Path(__file__).parent
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

import kopf
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config

from openstack_client import OpenStackClient
from resources.federation import FederationManager
from resources.network import delete_networks, ensure_networks
from resources.project import delete_project, ensure_project, get_project_info
from resources.quota import apply_quotas
from resources.role_binding import apply_role_bindings, get_users_from_role_bindings
from resources.security_group import delete_security_groups, ensure_security_groups
from utils import now_iso, set_condition

logger = logging.getLogger(__name__)

# Global OpenStack client (initialized on startup)
_os_client: OpenStackClient | None = None


def get_openstack_client() -> OpenStackClient:
    """Get or create the OpenStack client."""
    global _os_client
    if _os_client is None:
        _os_client = OpenStackClient()
    return _os_client


def get_federation_config(
    namespace: str, config_ref: dict[str, Any] | None
) -> dict[str, str] | None:
    """Load federation config from ConfigMap.

    Args:
        namespace: Namespace of the OpenstackProject CR
        config_ref: federationRef from the CR spec

    Returns:
        Dict with idp_name, idp_remote_id, sso_domain, or None
    """
    if not config_ref:
        return None

    cm_name = config_ref.get("configMapName")
    cm_namespace = config_ref.get("configMapNamespace", namespace)

    if not cm_name:
        return None

    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()

    v1 = k8s_client.CoreV1Api()
    try:
        cm = v1.read_namespaced_config_map(cm_name, cm_namespace)
        return {
            "idp_name": cm.data.get("idp-name", ""),
            "idp_remote_id": cm.data.get("idp-remote-id", ""),
            "sso_domain": cm.data.get("sso-domain", ""),
        }
    except k8s_client.ApiException as e:
        logger.error(f"Failed to read ConfigMap {cm_namespace}/{cm_name}: {e}")
        return None


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_: Any) -> None:
    """Configure operator settings on startup."""
    # Reduce logging noise
    settings.posting.level = logging.WARNING
    # Configure persistence
    settings.persistence.finalizer = "sunet.se/openstack-operator"
    # Set watching namespace - explicit cluster-wide or specific namespace
    # Can be overridden by WATCH_NAMESPACE env var
    watch_namespace = os.environ.get("WATCH_NAMESPACE", "")
    if watch_namespace:
        settings.watching.namespaces = [watch_namespace]
    else:
        settings.watching.clusterwide = True
    logger.info("OpenStack operator started")


@kopf.on.create("sunet.se", "v1alpha1", "openstackprojects")
def create_project(
    spec: dict[str, Any],
    status: dict[str, Any],
    patch: kopf.Patch,
    namespace: str,
    name: str,
    **_: Any,
) -> dict[str, Any]:
    """Handle OpenstackProject creation."""
    logger.info(f"Creating OpenstackProject: {namespace}/{name}")

    # Update status to Provisioning
    patch.status["phase"] = "Provisioning"
    patch.status["conditions"] = []

    client = get_openstack_client()
    result_status: dict[str, Any] = {"phase": "Provisioning"}

    try:
        # Extract spec values
        project_name = spec["name"]
        domain = spec["domain"]
        description = spec.get("description", "")
        enabled = spec.get("enabled", True)

        # 1. Create project and group
        set_condition(result_status, "ProjectReady", "False", "Creating", "")
        project_id, group_id = ensure_project(
            client, project_name, domain, description, enabled
        )
        result_status["projectId"] = project_id
        result_status["groupId"] = group_id
        set_condition(result_status, "ProjectReady", "True", "Created", "")

        # 2. Apply quotas
        quotas = spec.get("quotas", {})
        if quotas:
            set_condition(result_status, "QuotasReady", "False", "Applying", "")
            apply_quotas(client, project_id, quotas)
            set_condition(result_status, "QuotasReady", "True", "Applied", "")

        # 3. Create networks
        networks = spec.get("networks", [])
        if networks:
            set_condition(result_status, "NetworksReady", "False", "Creating", "")
            network_statuses = ensure_networks(client, project_id, networks)
            result_status["networks"] = network_statuses
            set_condition(result_status, "NetworksReady", "True", "Created", "")

        # 4. Create security groups
        security_groups = spec.get("securityGroups", [])
        if security_groups:
            set_condition(
                result_status, "SecurityGroupsReady", "False", "Creating", ""
            )
            sg_statuses = ensure_security_groups(client, project_id, security_groups)
            result_status["securityGroups"] = sg_statuses
            set_condition(result_status, "SecurityGroupsReady", "True", "Created", "")

        # 5. Apply role bindings
        role_bindings = spec.get("roleBindings", [])
        if role_bindings:
            apply_role_bindings(client, project_id, group_id, role_bindings, domain)

        # 6. Update federation mapping
        federation_ref = spec.get("federationRef")
        if federation_ref and role_bindings:
            fed_config = get_federation_config(namespace, federation_ref)
            if fed_config and fed_config["idp_name"]:
                set_condition(
                    result_status, "FederationReady", "False", "Configuring", ""
                )
                users = get_users_from_role_bindings(role_bindings)
                if users:
                    manager = FederationManager(
                        client,
                        fed_config["idp_name"],
                        fed_config["idp_remote_id"],
                        fed_config["sso_domain"],
                    )
                    manager.add_project_mapping(project_name, users)
                set_condition(
                    result_status, "FederationReady", "True", "Configured", ""
                )

        result_status["phase"] = "Ready"
        result_status["lastSyncTime"] = now_iso()
        logger.info(f"Successfully created OpenstackProject: {namespace}/{name}")

    except Exception as e:
        logger.error(f"Failed to create OpenstackProject {namespace}/{name}: {e}")
        result_status["phase"] = "Error"
        set_condition(
            result_status, "Ready", "False", "Error", str(e)[:200]
        )
        raise kopf.TemporaryError(f"Creation failed: {e}", delay=60)

    return result_status


@kopf.on.update("sunet.se", "v1alpha1", "openstackprojects")
def update_project(
    spec: dict[str, Any],
    status: dict[str, Any],
    patch: kopf.Patch,
    namespace: str,
    name: str,
    diff: kopf.Diff,
    **_: Any,
) -> dict[str, Any]:
    """Handle OpenstackProject updates."""
    logger.info(f"Updating OpenstackProject: {namespace}/{name}")

    client = get_openstack_client()
    result_status = dict(status)
    result_status["phase"] = "Provisioning"

    try:
        project_name = spec["name"]
        domain = spec["domain"]
        project_id = status.get("projectId")
        group_id = status.get("groupId")

        # If we don't have project_id, treat as create
        if not project_id:
            return create_project(
                spec=spec,
                status=status,
                patch=patch,
                namespace=namespace,
                name=name,
            )

        # Check what changed and update accordingly
        changed_paths = {change[1] for change in diff}

        # Update project description/enabled if changed
        if any(p[0] in ("description", "enabled") for p in changed_paths):
            description = spec.get("description", "")
            enabled = spec.get("enabled", True)
            client.update_project(project_id, description=description, enabled=enabled)

        # Update quotas if changed
        if any("quotas" in str(p) for p in changed_paths):
            quotas = spec.get("quotas", {})
            apply_quotas(client, project_id, quotas)
            set_condition(result_status, "QuotasReady", "True", "Updated", "")

        # Update networks if changed
        if any("networks" in str(p) for p in changed_paths):
            networks = spec.get("networks", [])
            # Delete old networks and create new ones
            old_networks = status.get("networks", [])
            delete_networks(client, old_networks)
            if networks:
                network_statuses = ensure_networks(client, project_id, networks)
                result_status["networks"] = network_statuses
            else:
                result_status["networks"] = []
            set_condition(result_status, "NetworksReady", "True", "Updated", "")

        # Update security groups if changed
        if any("securityGroups" in str(p) for p in changed_paths):
            security_groups = spec.get("securityGroups", [])
            # Delete old security groups and create new ones
            old_sgs = status.get("securityGroups", [])
            delete_security_groups(client, old_sgs)
            if security_groups:
                sg_statuses = ensure_security_groups(
                    client, project_id, security_groups
                )
                result_status["securityGroups"] = sg_statuses
            else:
                result_status["securityGroups"] = []
            set_condition(
                result_status, "SecurityGroupsReady", "True", "Updated", ""
            )

        # Update role bindings and federation if changed
        if any("roleBindings" in str(p) for p in changed_paths):
            role_bindings = spec.get("roleBindings", [])
            apply_role_bindings(
                client, project_id, group_id, role_bindings, domain
            )

            # Update federation mapping
            federation_ref = spec.get("federationRef")
            if federation_ref:
                fed_config = get_federation_config(namespace, federation_ref)
                if fed_config and fed_config["idp_name"]:
                    users = get_users_from_role_bindings(role_bindings)
                    manager = FederationManager(
                        client,
                        fed_config["idp_name"],
                        fed_config["idp_remote_id"],
                        fed_config["sso_domain"],
                    )
                    if users:
                        manager.add_project_mapping(project_name, users)
                    else:
                        manager.remove_project_mapping(project_name)
                    set_condition(
                        result_status, "FederationReady", "True", "Updated", ""
                    )

        result_status["phase"] = "Ready"
        result_status["lastSyncTime"] = now_iso()
        logger.info(f"Successfully updated OpenstackProject: {namespace}/{name}")

    except Exception as e:
        logger.error(f"Failed to update OpenstackProject {namespace}/{name}: {e}")
        result_status["phase"] = "Error"
        set_condition(result_status, "Ready", "False", "Error", str(e)[:200])
        raise kopf.TemporaryError(f"Update failed: {e}", delay=60)

    return result_status


@kopf.on.delete("sunet.se", "v1alpha1", "openstackprojects")
def delete_project_handler(
    spec: dict[str, Any],
    status: dict[str, Any],
    namespace: str,
    name: str,
    **_: Any,
) -> None:
    """Handle OpenstackProject deletion."""
    logger.info(f"Deleting OpenstackProject: {namespace}/{name}")

    client = get_openstack_client()

    project_name = spec["name"]
    domain = spec["domain"]
    project_id = status.get("projectId")
    group_id = status.get("groupId")

    if not project_id:
        logger.warning(
            f"No project_id in status for {namespace}/{name}, nothing to delete"
        )
        return

    try:
        # 1. Remove federation mapping
        federation_ref = spec.get("federationRef")
        if federation_ref:
            fed_config = get_federation_config(namespace, federation_ref)
            if fed_config and fed_config["idp_name"]:
                manager = FederationManager(
                    client,
                    fed_config["idp_name"],
                    fed_config["idp_remote_id"],
                    fed_config["sso_domain"],
                )
                manager.remove_project_mapping(project_name)

        # 2. Delete security groups
        sg_statuses = status.get("securityGroups", [])
        if sg_statuses:
            delete_security_groups(client, sg_statuses)

        # 3. Delete networks (routers, subnets, networks)
        network_statuses = status.get("networks", [])
        if network_statuses:
            delete_networks(client, network_statuses)

        # 4. Delete project and group
        delete_project(client, project_id, group_id, domain)

        logger.info(f"Successfully deleted OpenstackProject: {namespace}/{name}")

    except Exception as e:
        logger.error(f"Failed to delete OpenstackProject {namespace}/{name}: {e}")
        raise kopf.TemporaryError(f"Deletion failed: {e}", delay=60)


@kopf.timer("sunet.se", "v1alpha1", "openstackprojects", interval=300)
def reconcile_project(
    spec: dict[str, Any],
    status: dict[str, Any],
    patch: kopf.Patch,
    namespace: str,
    name: str,
    **_: Any,
) -> dict[str, Any] | None:
    """Periodic reconciliation to detect and repair drift."""
    if status.get("phase") != "Ready":
        logger.debug(
            f"Skipping reconciliation for {namespace}/{name}: phase is "
            f"{status.get('phase')}"
        )
        return None

    logger.debug(f"Reconciling OpenstackProject: {namespace}/{name}")

    client = get_openstack_client()
    project_name = spec["name"]
    domain = spec["domain"]

    try:
        # Verify project exists
        info = get_project_info(client, project_name, domain)
        if not info:
            logger.warning(
                f"Project {project_name} not found in OpenStack, triggering recreate"
            )
            # Clear status to trigger recreation
            return {
                "phase": "Pending",
                "projectId": None,
                "groupId": None,
            }

        # Verify project ID matches
        if info["project_id"] != status.get("projectId"):
            logger.warning(
                f"Project ID mismatch for {project_name}: "
                f"expected {status.get('projectId')}, got {info['project_id']}"
            )
            return {
                "phase": "Pending",
                "projectId": info["project_id"],
                "groupId": info["group_id"],
            }

        return {"lastSyncTime": now_iso()}

    except Exception as e:
        logger.error(f"Reconciliation failed for {namespace}/{name}: {e}")
        return None


def main() -> None:
    """Entry point for running the operator."""
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Kopf will be run via the CLI, but this allows direct invocation for testing
    logger.info("Starting OpenStack operator...")
    logger.info("Use 'kopf run src/handlers.py' to run the operator")
    sys.exit(0)


if __name__ == "__main__":
    main()
