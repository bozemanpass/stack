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

A deployment directory is self-contained: it holds the deployment's own copies of
everything the stack contributed, so `manage` reads nothing from the stack it was
deployed from.

```
deployment-dir/
├── compose/
│   └── composefile-<pod>.yml   one per pod, fixed up for this deployment
├── config/<name>/              config directories the pod files mount
├── configmaps/<name>/          k8s only: file trees that become ConfigMaps
├── data/<volume>/              volume directories, for a spec that maps them here
├── pods/<pod>/scripts/         the pod's pre/post-start scripts
├── config.env                  config values shared by every service
├── secrets.env                 generated secret values (0600)
├── .gitignore                  written alongside secrets.env, listing it
├── kubeconfig.yml              k8s only, when the spec gives a credential by path
├── deployment.yml              the deployment's cluster id
├── spec.yml                    copy of the spec it was deployed from
└── stack.yml                   copy of the stack (merged, for several specs)
```

Most entries appear only when the deployment has something to put in them: a stack
with no config directories gets no `config/`, and `pods/` exists only for a stack
whose pods declare a `pre_start_command` or `post_start_command` ([stack files
reference](../stack-files.md)).  Those scripts are copied in at deploy time and run
by `manage start` from the directory holding them, with `STACK_DEPLOYMENT_DIR` in
the environment — which is why they are copied at all rather than run from the
stack: like everything else here, the deployment keeps its own copy.

A stack's `create` hook can write further files of its own; see [hooks](../hooks.md).

## See Also

- [stack init](init.md) - Create a stack specification file
- [stack manage](manage.md) - Manage a deployed stack
- [stack prepare](prepare.md) - Build or download stack containers
