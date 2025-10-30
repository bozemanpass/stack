# stack manage

Manage a deployed stack (start, stop, etc.)

## Synopsis

```bash
stack manage --dir DEPLOYMENT_DIR COMMAND [ARGS]...
```

## Description

[Placeholder: Add detailed description of stack management operations and lifecycle]

## Global Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--dir` | TEXT | Path to deployment directory (required) | - |

## Subcommands

### start

Start the stack

```bash
stack manage --dir DEPLOYMENT_DIR start [OPTIONS] [EXTRA_ARGS]...
```

#### Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--stay-attached/--detatch-terminal` | FLAG | Stay attached to see container output | False |
| `--skip-cluster-management/--perform-cluster-management` | FLAG | Skip cluster initialization/tear-down (kind-k8s only) | False |

#### Arguments

- `EXTRA_ARGS`: Additional arguments passed to the underlying deployment tool

### stop

Stop the stack and remove the containers

```bash
stack manage --dir DEPLOYMENT_DIR stop [OPTIONS] [EXTRA_ARGS]...
```

#### Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--delete-volumes/--preserve-volumes` | FLAG | Delete data volumes | False |
| `--skip-cluster-management/--perform-cluster-management` | FLAG | Skip cluster initialization/tear-down (kind-k8s only) | False |

### ps

List running containers in the stack

```bash
stack manage --dir DEPLOYMENT_DIR ps
```

### status

Report stack and container status

```bash
stack manage --dir DEPLOYMENT_DIR status
```

### logs

Get logs for running containers

```bash
stack manage --dir DEPLOYMENT_DIR logs [OPTIONS] [EXTRA_ARGS]...
```

#### Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--tail`, `-n` | INTEGER | Number of lines to display | All |
| `--follow`, `-f` | FLAG | Follow log output | False |

### exec

Execute a command inside a container

```bash
stack manage --dir DEPLOYMENT_DIR exec [EXTRA_ARGS]...
```

#### Arguments

- `EXTRA_ARGS`: Container name and command to execute

### port

List mapped ports

```bash
stack manage --dir DEPLOYMENT_DIR port [EXTRA_ARGS]...
```

### push-images

Push container images/tags to the image registry

```bash
stack manage --dir DEPLOYMENT_DIR push-images
```

### reload

Reload the stack to pick up config changes

```bash
stack manage --dir DEPLOYMENT_DIR reload
```

### services

List stack service names

```bash
stack manage --dir DEPLOYMENT_DIR services
```

## Examples

### Starting and Stopping

```bash
# Start a stack
stack manage --dir ~/deployments/my-stack start

# Start and stay attached to see output
stack manage --dir ~/deployments/my-stack start --stay-attached

# Stop a stack (preserve volumes)
stack manage --dir ~/deployments/my-stack stop

# Stop and delete volumes
stack manage --dir ~/deployments/my-stack stop --delete-volumes
```

### Monitoring and Debugging

```bash
# Check status
stack manage --dir ~/deployments/my-stack status

# View logs
stack manage --dir ~/deployments/my-stack logs

# Follow logs for specific service
stack manage --dir ~/deployments/my-stack logs -f frontend

# Tail last 100 lines
stack manage --dir ~/deployments/my-stack logs -n 100

# List running containers
stack manage --dir ~/deployments/my-stack ps

# List services
stack manage --dir ~/deployments/my-stack services
```

### Container Operations

```bash
# Execute command in container
stack manage --dir ~/deployments/my-stack exec backend bash

# Check port mappings
stack manage --dir ~/deployments/my-stack port

# Push images to registry
stack manage --dir ~/deployments/my-stack push-images

# Reload configuration
stack manage --dir ~/deployments/my-stack reload
```

## See Also

- [stack deploy](deploy.md) - Deploy a stack
- [stack init](init.md) - Create a stack specification file
