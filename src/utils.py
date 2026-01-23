"""Utility functions for the OpenStack operator."""

import datetime
import re


def sanitize_name(name: str) -> str:
    """Convert a project name to a safe group/resource name.

    Replaces dots and underscores with hyphens, converts to lowercase,
    and removes any characters that aren't alphanumeric or hyphens.

    Example: 'My_Project.Example.COM' -> 'my-project-example-com'
    """
    sanitized = name.replace(".", "-").replace("_", "-").lower()
    sanitized = re.sub(r"[^a-z0-9-]", "", sanitized)
    sanitized = re.sub(r"-+", "-", sanitized)  # collapse multiple hyphens
    return sanitized.strip("-")


def make_group_name(project_name: str) -> str:
    """Generate a group name for a project's users.

    Example: 'my-project.example.com' -> 'my-project-example-com-users'
    """
    return f"{sanitize_name(project_name)}-users"


def now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.datetime.now(datetime.UTC).isoformat()
