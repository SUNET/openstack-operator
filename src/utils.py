"""Utility functions for the OpenStack operator."""

import datetime
import logging
from typing import Any

logger = logging.getLogger(__name__)


def sanitize_name(name: str) -> str:
    """Convert a project name to a safe group/resource name.

    Example: 'my-project.example.com' -> 'my-project-example-com'
    """
    return name.replace(".", "-").replace("_", "-").lower()


def make_group_name(project_name: str) -> str:
    """Generate a group name for a project's users.

    Example: 'my-project.example.com' -> 'my-project-example-com-users'
    """
    return f"{sanitize_name(project_name)}-users"


def now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.datetime.now(datetime.UTC).isoformat()


def set_condition(
    status: dict[str, Any],
    condition_type: str,
    condition_status: str,
    reason: str = "",
    message: str = "",
) -> None:
    """Set or update a condition in the status conditions list."""
    conditions = status.setdefault("conditions", [])

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


def get_condition_status(status: dict[str, Any], condition_type: str) -> str | None:
    """Get the status of a specific condition."""
    for condition in status.get("conditions", []):
        if condition["type"] == condition_type:
            return condition["status"]
    return None
