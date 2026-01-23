# OpenStack Project Operator

A Kopf-based Kubernetes operator for declaratively managing OpenStack projects, including:

- Projects and user groups
- Quotas (compute, storage, network)
- Networks, subnets, and routers
- Security groups and rules
- Role bindings
- Federation mappings for SSO access

## CRD: OpenstackProject

```yaml
apiVersion: sunet.se/v1alpha1
kind: OpenstackProject
metadata:
  name: my-project
spec:
  name: "my-project.example.com"
  description: "My OpenStack project"
  domain: "federated-users"
  enabled: true

  quotas:
    compute:
      instances: 20
      cores: 40
      ramMB: 81920
    storage:
      volumes: 20
      volumesGB: 1000
    network:
      floatingIps: 10

  networks:
    - name: internal
      cidr: 192.168.100.0/24
      enableDhcp: true
      router:
        externalNetwork: external
        enableSnat: true

  securityGroups:
    - name: allow-ssh
      rules:
        - direction: ingress
          protocol: tcp
          portRangeMin: 22
          portRangeMax: 22
          remoteIpPrefix: "0.0.0.0/0"

  roleBindings:
    - role: member
      users:
        - user1@example.com
        - user2@example.com
      userDomain: federated-users

  federationRef:
    configMapName: federation-config
```

## Building

```bash
# Build Docker image
docker build -t docker.sunet.se/platform/openstack-operator:latest .

# Or use Jenkins (see .jenkins.yaml)
```

## Deployment

The operator requires:

1. **OpenStack credentials** - A Secret with `clouds.yaml` containing admin credentials
2. **CRD installed** - The OpenstackProject CRD from `crds/`
3. **RBAC configured** - ServiceAccount with cluster-wide access to the CRD

Example deployment using kustomize:

```bash
# From a deployment overlay
kubectl apply -k overlays/test/
```

## Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Run locally (requires kubeconfig and OpenStack credentials)
export OS_CLOUD=openstack
export OS_CLIENT_CONFIG_FILE=/path/to/clouds.yaml
kopf run src/handlers.py --standalone

# Run tests
pytest
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OS_CLOUD` | Cloud name in clouds.yaml | `openstack` |
| `OS_CLIENT_CONFIG_FILE` | Path to clouds.yaml | Standard locations |
| `WATCH_NAMESPACE` | Namespace to watch (empty = all) | `""` |

### Federation ConfigMap

For SSO integration, create a ConfigMap with IdP settings:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: federation-config
data:
  idp-name: my-idp
  idp-remote-id: https://idp.example.com
  sso-domain: federated-users
```

Reference it in OpenstackProject via `federationRef`.

## Status

The operator maintains status on each OpenstackProject:

```yaml
status:
  phase: Ready  # Pending|Provisioning|Ready|Error|Deleting
  projectId: "abc123..."
  groupId: "def456..."
  networks:
    - name: internal
      networkId: "..."
      subnetId: "..."
      routerId: "..."
  securityGroups:
    - name: allow-ssh
      id: "..."
  conditions:
    - type: ProjectReady
      status: "True"
    - type: NetworksReady
      status: "True"
```

## License

MIT
