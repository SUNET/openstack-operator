"""OpenStack SDK wrapper with retry logic and connection management."""

import logging
import os
import time
from functools import wraps
from typing import Any, Callable, TypeVar

import openstack
from openstack.connection import Connection
from openstack.exceptions import ConflictException, HttpException, ResourceNotFound

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry_on_error(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (HttpException,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to retry operations on transient errors."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception = None
            current_delay = delay

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_retries + 1} failed for "
                            f"{func.__name__}: {e}. Retrying in {current_delay:.1f}s..."
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            f"All {max_retries + 1} attempts failed for {func.__name__}"
                        )

            raise last_exception  # type: ignore

        return wrapper

    return decorator


class OpenStackClient:
    """Wrapper around OpenStack SDK with convenience methods."""

    def __init__(
        self, cloud: str | None = None, clouds_config: str | None = None
    ) -> None:
        """Initialize OpenStack connection.

        Args:
            cloud: Cloud name from clouds.yaml (default: from OS_CLOUD env)
            clouds_config: Path to clouds.yaml (default: OS_CLIENT_CONFIG_FILE env)
        """
        self.cloud_name = cloud or os.environ.get("OS_CLOUD", "openstack")
        if clouds_config:
            os.environ["OS_CLIENT_CONFIG_FILE"] = clouds_config

        self._conn: Connection | None = None

    @property
    def conn(self) -> Connection:
        """Get or create OpenStack connection."""
        if self._conn is None:
            logger.info(f"Connecting to OpenStack cloud: {self.cloud_name}")
            self._conn = openstack.connect(cloud=self.cloud_name)
        return self._conn

    def close(self) -> None:
        """Close the OpenStack connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -------------------------------------------------------------------------
    # Domain operations
    # -------------------------------------------------------------------------

    @retry_on_error()
    def get_domain(self, name_or_id: str) -> Any | None:
        """Get a domain by name or ID."""
        return self.conn.identity.find_domain(name_or_id)

    # -------------------------------------------------------------------------
    # Project operations
    # -------------------------------------------------------------------------

    @retry_on_error()
    def get_project(self, name: str, domain: str) -> Any | None:
        """Get a project by name within a domain."""
        domain_obj = self.get_domain(domain)
        if not domain_obj:
            return None
        return self.conn.identity.find_project(name, domain_id=domain_obj.id)

    @retry_on_error()
    def create_project(
        self,
        name: str,
        domain: str,
        description: str = "",
        enabled: bool = True,
    ) -> Any:
        """Create a new project."""
        domain_obj = self.get_domain(domain)
        if not domain_obj:
            raise ValueError(f"Domain not found: {domain}")

        logger.info(f"Creating project: {name} in domain {domain}")
        return self.conn.identity.create_project(
            name=name,
            domain_id=domain_obj.id,
            description=description,
            is_enabled=enabled,
        )

    @retry_on_error()
    def update_project(
        self,
        project_id: str,
        description: str | None = None,
        enabled: bool | None = None,
    ) -> Any:
        """Update an existing project."""
        updates = {}
        if description is not None:
            updates["description"] = description
        if enabled is not None:
            updates["is_enabled"] = enabled

        if updates:
            logger.info(f"Updating project {project_id}: {updates}")
            return self.conn.identity.update_project(project_id, **updates)
        return self.conn.identity.get_project(project_id)

    @retry_on_error()
    def delete_project(self, project_id: str) -> None:
        """Delete a project."""
        logger.info(f"Deleting project: {project_id}")
        self.conn.identity.delete_project(project_id)

    # -------------------------------------------------------------------------
    # Group operations
    # -------------------------------------------------------------------------

    @retry_on_error()
    def get_group(self, name: str, domain: str) -> Any | None:
        """Get a group by name within a domain."""
        domain_obj = self.get_domain(domain)
        if not domain_obj:
            return None
        return self.conn.identity.find_group(name, domain_id=domain_obj.id)

    @retry_on_error()
    def create_group(self, name: str, domain: str, description: str = "") -> Any:
        """Create a new group."""
        domain_obj = self.get_domain(domain)
        if not domain_obj:
            raise ValueError(f"Domain not found: {domain}")

        logger.info(f"Creating group: {name} in domain {domain}")
        return self.conn.identity.create_group(
            name=name,
            domain_id=domain_obj.id,
            description=description,
        )

    @retry_on_error()
    def delete_group(self, group_id: str) -> None:
        """Delete a group."""
        logger.info(f"Deleting group: {group_id}")
        self.conn.identity.delete_group(group_id)

    # -------------------------------------------------------------------------
    # Role operations
    # -------------------------------------------------------------------------

    @retry_on_error()
    def get_role(self, name: str) -> Any | None:
        """Get a role by name."""
        return self.conn.identity.find_role(name)

    @retry_on_error()
    def assign_role_to_group(
        self, role_id: str, group_id: str, project_id: str
    ) -> None:
        """Assign a role to a group on a project."""
        logger.info(
            f"Assigning role {role_id} to group {group_id} on project {project_id}"
        )
        try:
            self.conn.identity.assign_project_role_to_group(
                project=project_id,
                group=group_id,
                role=role_id,
            )
        except ConflictException:
            logger.debug(f"Role {role_id} already assigned to group {group_id}")

    @retry_on_error()
    def revoke_role_from_group(
        self, role_id: str, group_id: str, project_id: str
    ) -> None:
        """Revoke a role from a group on a project."""
        logger.info(
            f"Revoking role {role_id} from group {group_id} on project {project_id}"
        )
        try:
            self.conn.identity.unassign_project_role_from_group(
                project=project_id,
                group=group_id,
                role=role_id,
            )
        except ResourceNotFound:
            logger.debug(f"Role {role_id} not assigned to group {group_id}")

    # -------------------------------------------------------------------------
    # Quota operations
    # -------------------------------------------------------------------------

    @retry_on_error()
    def set_compute_quotas(self, project_id: str, quotas: dict[str, int]) -> None:
        """Set compute quotas for a project."""
        if not quotas:
            return

        logger.info(f"Setting compute quotas for project {project_id}: {quotas}")
        quota_args = {}
        if "instances" in quotas:
            quota_args["instances"] = quotas["instances"]
        if "cores" in quotas:
            quota_args["cores"] = quotas["cores"]
        if "ramMB" in quotas:
            quota_args["ram"] = quotas["ramMB"]
        if "serverGroups" in quotas:
            quota_args["server_groups"] = quotas["serverGroups"]
        if "serverGroupMembers" in quotas:
            quota_args["server_group_members"] = quotas["serverGroupMembers"]

        if quota_args:
            self.conn.compute.update_quota_set(project_id, **quota_args)

    @retry_on_error()
    def set_volume_quotas(self, project_id: str, quotas: dict[str, int]) -> None:
        """Set volume quotas for a project."""
        if not quotas:
            return

        logger.info(f"Setting volume quotas for project {project_id}: {quotas}")
        quota_args = {}
        if "volumes" in quotas:
            quota_args["volumes"] = quotas["volumes"]
        if "volumesGB" in quotas:
            quota_args["gigabytes"] = quotas["volumesGB"]
        if "snapshots" in quotas:
            quota_args["snapshots"] = quotas["snapshots"]
        if "backups" in quotas:
            quota_args["backups"] = quotas["backups"]
        if "backupsGB" in quotas:
            quota_args["backup_gigabytes"] = quotas["backupsGB"]

        if quota_args:
            self.conn.block_storage.update_quota_set(project_id, **quota_args)

    @retry_on_error()
    def set_network_quotas(self, project_id: str, quotas: dict[str, int]) -> None:
        """Set network quotas for a project."""
        if not quotas:
            return

        logger.info(f"Setting network quotas for project {project_id}: {quotas}")
        quota_args = {}
        if "floatingIps" in quotas:
            quota_args["floatingip"] = quotas["floatingIps"]
        if "networks" in quotas:
            quota_args["network"] = quotas["networks"]
        if "subnets" in quotas:
            quota_args["subnet"] = quotas["subnets"]
        if "routers" in quotas:
            quota_args["router"] = quotas["routers"]
        if "ports" in quotas:
            quota_args["port"] = quotas["ports"]
        if "securityGroups" in quotas:
            quota_args["security_group"] = quotas["securityGroups"]
        if "securityGroupRules" in quotas:
            quota_args["security_group_rule"] = quotas["securityGroupRules"]

        if quota_args:
            self.conn.network.update_quota(project_id, **quota_args)

    # -------------------------------------------------------------------------
    # Network operations
    # -------------------------------------------------------------------------

    @retry_on_error()
    def get_network(self, name: str, project_id: str) -> Any | None:
        """Get a network by name within a project."""
        networks = list(self.conn.network.networks(name=name, project_id=project_id))
        return networks[0] if networks else None

    @retry_on_error()
    def create_network(self, name: str, project_id: str) -> Any:
        """Create a network."""
        logger.info(f"Creating network: {name} in project {project_id}")
        return self.conn.network.create_network(name=name, project_id=project_id)

    @retry_on_error()
    def delete_network(self, network_id: str) -> None:
        """Delete a network."""
        logger.info(f"Deleting network: {network_id}")
        self.conn.network.delete_network(network_id)

    @retry_on_error()
    def get_subnet(self, name: str, network_id: str) -> Any | None:
        """Get a subnet by name within a network."""
        subnets = list(self.conn.network.subnets(name=name, network_id=network_id))
        return subnets[0] if subnets else None

    @retry_on_error()
    def create_subnet(
        self,
        name: str,
        network_id: str,
        cidr: str,
        enable_dhcp: bool = True,
        dns_nameservers: list[str] | None = None,
    ) -> Any:
        """Create a subnet."""
        logger.info(f"Creating subnet: {name} with CIDR {cidr}")
        return self.conn.network.create_subnet(
            name=name,
            network_id=network_id,
            cidr=cidr,
            ip_version=4,
            is_dhcp_enabled=enable_dhcp,
            dns_nameservers=dns_nameservers or [],
        )

    @retry_on_error()
    def delete_subnet(self, subnet_id: str) -> None:
        """Delete a subnet."""
        logger.info(f"Deleting subnet: {subnet_id}")
        self.conn.network.delete_subnet(subnet_id)

    @retry_on_error()
    def get_router(self, name: str, project_id: str) -> Any | None:
        """Get a router by name within a project."""
        routers = list(self.conn.network.routers(name=name, project_id=project_id))
        return routers[0] if routers else None

    @retry_on_error()
    def create_router(
        self,
        name: str,
        project_id: str,
        external_network_id: str | None = None,
        enable_snat: bool = True,
    ) -> Any:
        """Create a router."""
        logger.info(f"Creating router: {name} in project {project_id}")
        external_gateway_info = None
        if external_network_id:
            external_gateway_info = {
                "network_id": external_network_id,
                "enable_snat": enable_snat,
            }
        return self.conn.network.create_router(
            name=name,
            project_id=project_id,
            external_gateway_info=external_gateway_info,
        )

    @retry_on_error()
    def add_router_interface(self, router_id: str, subnet_id: str) -> None:
        """Add a subnet interface to a router."""
        logger.info(f"Adding interface for subnet {subnet_id} to router {router_id}")
        try:
            self.conn.network.add_interface_to_router(router_id, subnet_id=subnet_id)
        except ConflictException:
            logger.debug(
                f"Interface for subnet {subnet_id} already on router {router_id}"
            )

    @retry_on_error()
    def remove_router_interface(self, router_id: str, subnet_id: str) -> None:
        """Remove a subnet interface from a router."""
        logger.info(
            f"Removing interface for subnet {subnet_id} from router {router_id}"
        )
        try:
            self.conn.network.remove_interface_from_router(router_id, subnet_id=subnet_id)
        except ResourceNotFound:
            logger.debug(f"Interface for subnet {subnet_id} not on router {router_id}")

    @retry_on_error()
    def delete_router(self, router_id: str) -> None:
        """Delete a router."""
        logger.info(f"Deleting router: {router_id}")
        self.conn.network.delete_router(router_id)

    @retry_on_error()
    def get_external_network(self, name: str) -> Any | None:
        """Get an external network by name."""
        networks = list(self.conn.network.networks(name=name, is_router_external=True))
        return networks[0] if networks else None

    # -------------------------------------------------------------------------
    # Security group operations
    # -------------------------------------------------------------------------

    @retry_on_error()
    def get_security_group(self, name: str, project_id: str) -> Any | None:
        """Get a security group by name within a project."""
        sgs = list(self.conn.network.security_groups(name=name, project_id=project_id))
        return sgs[0] if sgs else None

    @retry_on_error()
    def create_security_group(
        self, name: str, project_id: str, description: str = ""
    ) -> Any:
        """Create a security group."""
        logger.info(f"Creating security group: {name} in project {project_id}")
        return self.conn.network.create_security_group(
            name=name,
            project_id=project_id,
            description=description,
        )

    @retry_on_error()
    def delete_security_group(self, sg_id: str) -> None:
        """Delete a security group."""
        logger.info(f"Deleting security group: {sg_id}")
        self.conn.network.delete_security_group(sg_id)

    @retry_on_error()
    def create_security_group_rule(
        self,
        security_group_id: str,
        direction: str,
        protocol: str | None = None,
        port_range_min: int | None = None,
        port_range_max: int | None = None,
        remote_ip_prefix: str | None = None,
        remote_group_id: str | None = None,
        ethertype: str = "IPv4",
    ) -> Any:
        """Create a security group rule."""
        logger.info(
            f"Creating security group rule: {direction} {protocol} "
            f"{port_range_min}-{port_range_max} in {security_group_id}"
        )
        try:
            return self.conn.network.create_security_group_rule(
                security_group_id=security_group_id,
                direction=direction,
                protocol=protocol if protocol != "any" else None,
                port_range_min=port_range_min,
                port_range_max=port_range_max,
                remote_ip_prefix=remote_ip_prefix,
                remote_group_id=remote_group_id,
                ether_type=ethertype,
            )
        except ConflictException:
            logger.debug("Security group rule already exists")
            return None

    # -------------------------------------------------------------------------
    # Federation operations
    # -------------------------------------------------------------------------

    @retry_on_error()
    def get_identity_provider(self, idp_id: str) -> Any | None:
        """Get an identity provider by ID."""
        try:
            return self.conn.identity.get_identity_provider(idp_id)
        except ResourceNotFound:
            return None

    @retry_on_error()
    def create_identity_provider(self, idp_id: str, remote_ids: list[str]) -> Any:
        """Create an identity provider."""
        logger.info(f"Creating identity provider: {idp_id}")
        return self.conn.identity.create_identity_provider(
            id=idp_id,
            remote_ids=remote_ids,
            is_enabled=True,
        )

    @retry_on_error()
    def get_mapping(self, mapping_id: str) -> Any | None:
        """Get a federation mapping by ID."""
        try:
            return self.conn.identity.get_mapping(mapping_id)
        except ResourceNotFound:
            return None

    @retry_on_error()
    def create_mapping(self, mapping_id: str, rules: list[dict]) -> Any:
        """Create a federation mapping."""
        logger.info(f"Creating mapping: {mapping_id}")
        return self.conn.identity.create_mapping(id=mapping_id, rules=rules)

    @retry_on_error()
    def update_mapping(self, mapping_id: str, rules: list[dict]) -> Any:
        """Update a federation mapping."""
        logger.info(f"Updating mapping: {mapping_id}")
        return self.conn.identity.update_mapping(mapping_id, rules=rules)

    @retry_on_error()
    def get_federation_protocol(self, idp_id: str, protocol_id: str) -> Any | None:
        """Get a federation protocol."""
        try:
            return self.conn.identity.get_federation_protocol(protocol_id, idp_id)
        except ResourceNotFound:
            return None

    @retry_on_error()
    def create_federation_protocol(
        self, idp_id: str, protocol_id: str, mapping_id: str
    ) -> Any:
        """Create a federation protocol."""
        logger.info(f"Creating federation protocol: {protocol_id} for IdP {idp_id}")
        return self.conn.identity.create_federation_protocol(
            protocol_id,
            idp_id,
            mapping_id=mapping_id,
        )
