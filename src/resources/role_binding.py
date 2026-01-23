"""Role binding management for OpenStack projects."""

import logging
from typing import Any

from openstack_client import OpenStackClient

logger = logging.getLogger(__name__)


def apply_role_bindings(
    client: OpenStackClient,
    project_id: str,
    group_id: str,
    role_bindings: list[dict[str, Any]],
    project_domain: str,
) -> None:
    """Apply role bindings to a project.

    For now, this focuses on ensuring the project's user group has the
    correct roles assigned. User management is handled via federation
    mappings, not direct user-role assignments.

    Args:
        client: OpenStack client
        project_id: Project ID
        group_id: Project's user group ID
        role_bindings: List of role binding specifications
        project_domain: Domain of the project
    """
    if not role_bindings:
        logger.debug(f"No role bindings specified for project {project_id}")
        return

    for binding in role_bindings:
        role_name = binding["role"]
        role = client.get_role(role_name)
        if not role:
            logger.warning(f"Role {role_name} not found, skipping")
            continue

        # Always assign the role to the project's user group
        # This is required for federated users who are placed in this group
        # via the federation mapping
        if group_id:
            client.assign_role_to_group(role.id, group_id, project_id)
            logger.info(
                f"Assigned role {role_name} to project group {group_id} "
                f"on project {project_id}"
            )

        # Handle additional explicit group bindings
        groups = binding.get("groups", [])
        group_domain = binding.get("groupDomain", project_domain)

        for group_name in groups:
            group = client.get_group(group_name, group_domain)
            if group:
                client.assign_role_to_group(role.id, group.id, project_id)
                logger.info(
                    f"Assigned role {role_name} to group {group_name} "
                    f"on project {project_id}"
                )
            else:
                logger.warning(
                    f"Group {group_name} not found in domain {group_domain}"
                )

        # Add users to the project group directly
        # Users are identified by their OIDC sub claim (used as username)
        # This is required for features like application credentials
        users = binding.get("users", [])
        user_domain = binding.get("userDomain", project_domain)
        if users and group_id:
            _add_users_to_group(client, users, user_domain, group_id)


def _add_users_to_group(
    client: OpenStackClient,
    users: list[str],
    user_domain: str,
    group_id: str,
) -> None:
    """Add users to a group by their OIDC sub (username).

    Users must already exist in the domain (created via federation on first login).
    Users that don't exist yet are skipped - they'll be added on next reconciliation
    after their first SSO login.
    """
    for username in users:
        user = client.get_user(username, user_domain)
        if user:
            client.add_user_to_group(user.id, group_id)
            logger.info(f"Added user {username} to group {group_id}")
        else:
            logger.debug(
                f"User {username} not found in domain {user_domain}, "
                "will be added after first SSO login"
            )


def get_users_from_role_bindings(
    role_bindings: list[dict[str, Any]],
) -> list[str]:
    """Extract all users from role bindings.

    These users will be added to the federation mapping.
    """
    users: list[str] = []
    for binding in role_bindings:
        binding_users = binding.get("users", [])
        for user in binding_users:
            if user not in users:
                users.append(user)
    return users
