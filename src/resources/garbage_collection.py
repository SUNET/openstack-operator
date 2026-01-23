"""Garbage collection for orphaned OpenStack resources."""

import logging
from typing import Any

from openstack_client import OpenStackClient
from resources.project import MANAGED_BY_TAG

logger = logging.getLogger(__name__)


def collect_garbage(
    client: OpenStackClient,
    managed_domain: str,
    expected_projects: set[str],
) -> dict[str, list[str]]:
    """Remove orphaned projects and groups from managed domain.

    Only deletes projects that have the managed-by tag AND don't have
    a corresponding OpenstackProject CR. This ensures we never delete
    resources created outside the operator.

    Args:
        client: OpenStack client
        managed_domain: Domain name to scan for orphans (e.g., 'sso-users')
        expected_projects: Set of project names that should exist (from CRs)

    Returns:
        Dict with 'deleted_projects' and 'deleted_groups' lists
    """
    result: dict[str, list[str]] = {
        "deleted_projects": [],
        "deleted_groups": [],
    }

    domain = client.get_domain(managed_domain)
    if not domain:
        logger.warning(f"Domain {managed_domain} not found, skipping GC")
        return result

    # Get only operator-managed projects (those with our tag)
    projects = client.list_projects_with_tag(domain.id, MANAGED_BY_TAG)
    logger.debug(f"Found {len(projects)} operator-managed projects in {managed_domain}")

    for project in projects:
        if project.name not in expected_projects:
            logger.info(
                f"Found orphaned project {project.name} in domain {managed_domain}"
            )

            # Find and delete associated group (naming convention: <project>-users with . replaced by -)
            group_name = project.name.replace(".", "-") + "-users"
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

    return result


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
