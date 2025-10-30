# stack init

Create a stack specification file

## Synopsis

```bash
stack init [OPTIONS]
```

## Description

[Placeholder: Add detailed description of how init generates deployment specifications from stack definitions]

## Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--stack` | TEXT | Name or path of the stack | - |
| `--git-ssh/--no-git-ssh` | FLAG | Use SSH for git rather than HTTPS | From config |
| `--config` | TEXT | Provide config variables for the deployment (can be used multiple times) | - |
| `--config-file` | TEXT | Provide config variables in a file for the deployment | - |
| `--cluster` | TEXT | Specify a non-default cluster name | - |
| `--deploy-to` | CHOICE | Cluster system to deploy to (`compose`, `k8s`, or `k8s-kind`) | From config or `compose` |
| `--kube-config` | TEXT | Provide a config file for a k8s deployment | From config |
| `--image-registry` | TEXT | Container image registry URL for this k8s cluster | From config |
| `--http-proxy-target` | TEXT | k8s http proxy settings in format: `target_svc:target_port[path]` (multiple) | - |
| `--http-proxy-fqdn` | TEXT | k8s http proxy hostname to use | From config |
| `--http-proxy-clusterissuer` | TEXT | k8s http proxy cluster issuer | From config or `letsencrypt-prod` |
| `--output` | TEXT | Write yaml spec file here (required) | - |
| `--map-ports-to-host` | CHOICE | Port mapping strategy | See below |

## Port Mapping Strategies

| Strategy | Description | Use Case |
|----------|-------------|----------|
| `any-variable-random` | Docker default - random ports on any interface | Development |
| `localhost-same` | Same ports on localhost only | Local development |
| `any-same` | Same ports on any interface | Production-like local |
| `localhost-fixed-random` | Fixed random ports on localhost | Consistent local dev |
| `any-fixed-random` | Fixed random ports on any interface | Consistent testing |
| `k8s-clusterip-same` | K8s default - ClusterIP with same ports | Kubernetes |

## Configuration Variables

Configuration variables can be provided in two ways:

1. **Command line**: `--config KEY=VALUE`
2. **Config file**: `--config-file path/to/config.env`

Config file format:
```env
DB_HOST=localhost
DB_PORT=5432
API_KEY=secret123
```

## Examples

### Docker Compose Deployment

```bash
# Basic compose deployment
stack init --stack my-stack --output my-stack.yml --deploy-to compose

# With port mapping
stack init --stack my-stack --output my-stack.yml \
  --deploy-to compose --map-ports-to-host localhost-same

# With configuration
stack init --stack my-stack --output my-stack.yml \
  --config DB_HOST=postgres --config API_PORT=8080
```

### Kubernetes Deployment

```bash
# Basic k8s deployment
stack init --stack my-stack --output my-stack.yml \
  --deploy-to k8s --image-registry registry.example.com

# With HTTP proxy
stack init --stack my-stack --output my-stack.yml \
  --deploy-to k8s \
  --http-proxy-fqdn my-app.example.com \
  --http-proxy-target frontend:3000

# Kind (Kubernetes in Docker)
stack init --stack my-stack --output my-stack.yml \
  --deploy-to k8s-kind --cluster local-dev
```

## Output Format

The generated specification file contains:
- Stack definition
- Deployment target configuration
- Container specifications
- Network and volume definitions
- Configuration variables
- Port mappings

## See Also

- [stack deploy](deploy.md) - Deploy a stack
- [stack config](config.md) - Manage configuration settings
- [stack prepare](prepare.md) - Build or download stack containers
