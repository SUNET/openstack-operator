"""Image resource management for OpenStack operator."""

import logging
from typing import Any

from openstack_client import OpenStackClient

logger = logging.getLogger(__name__)


def ensure_image(
    client: OpenStackClient,
    spec: dict[str, Any],
) -> tuple[str, str]:
    """Ensure an image exists with the given configuration.

    Creates the image metadata and initiates web-download import if it doesn't exist.
    The import is asynchronous - callers should poll the status.

    Args:
        client: OpenStack client
        spec: Image specification from CRD

    Returns:
        Tuple of (image_id, upload_status)
    """
    name = spec["name"]
    existing = client.get_image(name)

    if existing:
        logger.info(f"Image {name} already exists (id={existing.id})")
        # Update mutable properties
        visibility = spec.get("visibility", "private")
        protected = spec.get("protected", False)
        tags = spec.get("tags", [])
        properties = spec.get("properties", {})

        client.update_image(
            existing.id,
            visibility=visibility,
            protected=protected,
            tags=tags,
            properties=properties,
        )
        return existing.id, existing.status

    # Create new image
    content = spec["content"]
    image = client.create_image(
        name=name,
        disk_format=content["diskFormat"],
        container_format=content.get("containerFormat", "bare"),
        visibility=spec.get("visibility", "private"),
        protected=spec.get("protected", False),
        tags=spec.get("tags"),
        properties=spec.get("properties"),
    )
    logger.info(f"Created image {name} (id={image.id})")

    # Start web-download import
    source = content.get("source", {})
    url = source.get("url")
    if url:
        logger.info(f"Starting web-download for image {name} from {url}")
        client.import_image_from_url(image.id, url)

    # Get current status after import initiation
    updated_image = client.get_image_by_id(image.id)
    status = updated_image.status if updated_image else "queued"

    return image.id, status


def get_image_status(
    client: OpenStackClient,
    image_id: str,
) -> dict[str, Any] | None:
    """Get current image status.

    Args:
        client: OpenStack client
        image_id: The image ID

    Returns:
        Dict with status, checksum, size, or None if not found
    """
    image = client.get_image_by_id(image_id)
    if not image:
        return None

    return {
        "status": image.status,
        "checksum": getattr(image, "checksum", None),
        "size": getattr(image, "size", None),
    }


def delete_image(client: OpenStackClient, image_id: str) -> None:
    """Delete an image.

    Note: Protected images are automatically unprotected before deletion.

    Args:
        client: OpenStack client
        image_id: The image ID to delete
    """
    client.delete_image(image_id)
