"""Prometheus metrics for the OpenStack operator."""

from prometheus_client import Counter, Histogram, Gauge, Info

# Reconciliation metrics
RECONCILE_TOTAL = Counter(
    "openstack_operator_reconcile_total",
    "Total number of reconciliations",
    ["resource", "operation", "status"],
)

RECONCILE_DURATION = Histogram(
    "openstack_operator_reconcile_duration_seconds",
    "Time spent in reconciliation",
    ["resource", "operation"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

RECONCILE_IN_PROGRESS = Gauge(
    "openstack_operator_reconcile_in_progress",
    "Number of reconciliations currently in progress",
    ["resource"],
)

# OpenStack API metrics
OPENSTACK_API_CALLS = Counter(
    "openstack_operator_openstack_api_calls_total",
    "Total number of OpenStack API calls",
    ["service", "operation", "status"],
)

OPENSTACK_API_DURATION = Histogram(
    "openstack_operator_openstack_api_duration_seconds",
    "Time spent in OpenStack API calls",
    ["service", "operation"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

OPENSTACK_API_RETRIES = Counter(
    "openstack_operator_openstack_api_retries_total",
    "Total number of OpenStack API call retries",
    ["service", "operation"],
)

RATE_LIMIT_WAIT_SECONDS = Histogram(
    "openstack_operator_rate_limit_wait_seconds",
    "Time spent waiting for rate limit slot",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

# Resource state metrics
MANAGED_RESOURCES = Gauge(
    "openstack_operator_managed_resources",
    "Number of managed resources by type and phase",
    ["resource", "phase"],
)

# Garbage collection metrics - cluster-scoped (domains, flavors, images, networks)
CLUSTER_GC_RUNS = Counter(
    "openstack_operator_cluster_gc_runs_total",
    "Total number of cluster-scoped garbage collection runs",
    ["status"],
)

CLUSTER_GC_DELETED_RESOURCES = Counter(
    "openstack_operator_cluster_gc_deleted_resources_total",
    "Total number of cluster-scoped resources deleted by garbage collection",
    ["resource_type"],
)

CLUSTER_GC_DURATION = Histogram(
    "openstack_operator_cluster_gc_duration_seconds",
    "Time spent in cluster-scoped garbage collection",
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)

# Garbage collection metrics - namespace-scoped (projects)
PROJECT_GC_RUNS = Counter(
    "openstack_operator_project_gc_runs_total",
    "Total number of project garbage collection runs",
    ["status"],
)

PROJECT_GC_DELETED_RESOURCES = Counter(
    "openstack_operator_project_gc_deleted_resources_total",
    "Total number of project resources deleted by garbage collection",
    ["resource_type"],
)

PROJECT_GC_DURATION = Histogram(
    "openstack_operator_project_gc_duration_seconds",
    "Time spent in project garbage collection",
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)

# Operator info
OPERATOR_INFO = Info(
    "openstack_operator",
    "Information about the OpenStack operator",
)


def set_operator_info(version: str, cloud: str) -> None:
    """Set operator info labels."""
    OPERATOR_INFO.info({"version": version, "cloud": cloud})
