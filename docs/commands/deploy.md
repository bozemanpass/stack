# stack deploy

Deploy a stack

## Synopsis

```bash
stack deploy [OPTIONS]
```

## Description

[Placeholder: Add detailed description of the deployment process, including how it creates deployment artifacts from spec files]

## Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--cluster` | TEXT | Specify a non-default cluster name | - |
| `--spec-file` | TEXT | Spec file to use to create this deployment (required, can be used multiple times) | - |
| `--deployment-dir` | TEXT | Create deployment files in this directory | - |

## Deployment Process

1. Reads the specification file(s)
2. Creates deployment directory structure
3. Generates deployment artifacts (docker-compose.yml or k8s manifests)
4. Prepares configuration files
5. Sets up volumes and networking

## Deployment Targets

The deployment target is specified in the spec file and can be:
- `compose`: Docker Compose deployment
- `k8s`: Kubernetes deployment
- `k8s-kind`: Kubernetes in Docker (kind) deployment

## Examples

```bash
# Deploy using a single spec file
stack deploy --spec-file my-stack.yml --deployment-dir ~/deployments/my-stack

# Deploy with multiple spec files
stack deploy --spec-file base.yml --spec-file overrides.yml --deployment-dir ~/deployments/my-stack

# Deploy to a specific cluster
stack deploy --spec-file my-stack.yml --cluster staging --deployment-dir ~/deployments/staging
```

## Directory Structure

The deployment directory will contain:
```
deployment-dir/
├── compose/           # For Docker Compose deployments
│   └── docker-compose.yml
├── k8s/              # For Kubernetes deployments
│   ├── manifests/
│   └── configmaps/
├── config/           # Configuration files
└── spec.yml          # Copy of deployment spec
```

## See Also

- [stack init](init.md) - Create a stack specification file
- [stack manage](manage.md) - Manage a deployed stack
- [stack prepare](prepare.md) - Build or download stack containers
