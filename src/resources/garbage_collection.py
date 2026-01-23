"""Garbage collection for orphaned OpenStack resources."""

import logging
from typing import Any

from constants import MANAGED_BY_TAG
from openstack_client import OpenStackClient
from resources.federation import FederationManager
from utils import make_group_name

logger = logging.getLogger(__name__)


def collect_garbage(
    client: OpenStackClient,
    managed_domain: str,
    expected_projects: set[str],
    federation_config: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """Remove orphaned projects, groups, and federation mappings.

    Only deletes projects that have the managed-by tag AND don't have
    a corresponding OpenstackProject CR. This ensures we never delete
    resources created outside the operator.

    Args:
        client: OpenStack client
        managed_domain: Domain name to scan for orphans (e.g., 'sso-users')
        expected_projects: Set of project names that should exist (from CRs)
        federation_config: Optional dict with idp_name, idp_remote_id, sso_domain

    Returns:
        Dict with 'deleted_projects', 'deleted_groups', 'deleted_mappings' lists
    """
    result: dict[str, list[str]] = {
        "deleted_projects": [],
        "deleted_groups": [],
        "deleted_mappings": [],
    }

    domain = client.get_domain(managed_domain)
    if not domain:
        logger.warning(f"Domain {managed_domain} not found, skipping GC")
        return result

    # Get only operator-managed projects (those with our tag)
    projects = client.list_projects_with_tag(domain.id, MANAGED_BY_TAG)
    logger.debug(f"Found {len(projects)} operator-managed projects in {managed_domain}")

    orphaned_projects: list[str] = []

    for project in projects:
        if project.name not in expected_projects:
            logger.info(
                f"Found orphaned project {project.name} in domain {managed_domain}"
            )
            orphaned_projects.append(project.name)

            # Find and delete associated group
            group_name = make_group_name(project.name)
            group = client.get_group(group_name, managed_domain)
            if group:
                try:
                    client.delete_group(group.id)
                    result["deleted_groups"].append(group_name)
                    logger.info(f"Deleted orphaned group {group_name}")
                except Exception as e:
                    logger.error(f"Failed to delete group {group_name}: {e}")

            # Delete the project
            try:
                client.delete_project(project.id)
                result["deleted_projects"].append(project.name)
                logger.info(f"Deleted orphaned project {project.name}")
            except Exception as e:
                logger.error(f"Failed to delete project {project.name}: {e}")

    # Clean up federation mappings for orphaned projects
    if federation_config and orphaned_projects:
        _cleanup_federation_mappings(
            client, federation_config, orphaned_projects, result
        )

    return result


def _cleanup_federation_mappings(
    client: OpenStackClient,
    federation_config: dict[str, str],
    orphaned_projects: list[str],
    result: dict[str, list[str]],
) -> None:
    """Remove federation mapping rules for orphaned projects."""
    try:
        manager = FederationManager(
            client,
            federation_config["idp_name"],
            federation_config["idp_remote_id"],
            federation_config["sso_domain"],
        )

        for project_name in orphaned_projects:
            try:
                manager.remove_project_mapping(project_name)
                result["deleted_mappings"].append(project_name)
                logger.info(f"Removed federation mapping for orphaned project {project_name}")
            except Exception as e:
                logger.error(
                    f"Failed to remove federation mapping for {project_name}: {e}"
                )
    except Exception as e:
        logger.error(f"Failed to initialize FederationManager for GC: {e}")


def get_expected_projects_from_crs(
    cr_list: list[dict[str, Any]],
) -> set[str]:
    """Extract expected project names from OpenstackProject CRs.

    Args:
        cr_list: List of OpenstackProject CR dicts

    Returns:
        Set of project names that should exist
    """
    expected: set[str] = set()
    for cr in cr_list:
        spec = cr.get("spec", {})
        project_name = spec.get("name")
        if project_name:
            expected.add(project_name)
    return expected


def get_federation_config_from_crs(
    cr_list: list[dict[str, Any]],
    k8s_core_api: Any,
) -> dict[str, str] | None:
    """Extract federation config from the first CR that has one.

    Args:
        cr_list: List of OpenstackProject CR dicts
        k8s_core_api: Kubernetes CoreV1Api instance

    Returns:
        Dict with idp_name, idp_remote_id, sso_domain or None
    """
    for cr in cr_list:
        spec = cr.get("spec", {})
        federation_ref = spec.get("federationRef")
        if federation_ref:
            config_map_name = federation_ref.get("configMapName")
            config_map_ns = federation_ref.get("configMapNamespace")
            if config_map_name and config_map_ns:
                try:
                    cm = k8s_core_api.read_namespaced_config_map(
                        config_map_name, config_map_ns
                    )
                    data = cm.data or {}
                    if data.get("IDP_NAME"):
                        return {
                            "idp_name": data.get("IDP_NAME", ""),
                            "idp_remote_id": data.get("IDP_REMOTE_ID", ""),
                            "sso_domain": data.get("SSO_DOMAIN", ""),
                        }
                except Exception as e:
                    logger.debug(f"Could not read federation config: {e}")
                    continue
    return None
