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

Only images the deployment will pull from the staging registry are uploaded.
An image that is already published to its canonical registry is deployed under
that reference and is skipped here. See
[image-names.md](../image-names.md) for the resolution order.

### reload

Reload the stack to pick up config changes

```bash
stack manage --dir DEPLOYMENT_DIR reload
```

### backup

Back up and restore the deployment's data

```bash
stack manage --dir DEPLOYMENT_DIR backup SUBCOMMAND [OPTIONS]
```

Backups run automatically on a schedule once backup is configured for the
environment; these subcommands operate on an existing deployment's backups.
There is nothing backup-specific in the stack or the spec — what to back up is
derived from the deployment, and where to send it comes from configuration
(see [stack config](config.md#configuration-keys) and [backup.md](../backup.md)).

#### backup now

Back up the deployment's data immediately, outside the schedule, and wait for it.

```bash
stack manage --dir DEPLOYMENT_DIR backup now
```

#### backup list

List the snapshots available to restore, one line per snapshot — id, time, and
the volumes it holds. Each volume is backed up as its own snapshot.

```bash
stack manage --dir DEPLOYMENT_DIR backup list
```

#### backup restore

Restore the deployment's data from a snapshot, in place, into the deployment's
existing volumes.

```bash
stack manage --dir DEPLOYMENT_DIR backup restore [OPTIONS]
```

##### Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--snapshot` | TEXT | Snapshot to restore | `latest` |
| `--volume` | TEXT | Restore only this volume (repeatable) | All volumes |
| `--from` | TEXT | Restore from another deployment's backups, naming it | This deployment's own |

Restoring underneath a running service overwrites files it has open, so stopping
the deployment first is the operator's job. A deployment restored with `--from`
keeps its own identity and goes on backing up to its own repository, which is
what makes it the disaster-recovery and seed-a-copy path.

Restoring a dump taken by an `@stack backup-command` is manual and external:
`backup restore` fills volumes, and a dump is not a volume. See
[backup.md](../backup.md#application-consistency).

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

### Backup and Restore

```bash
# Take a backup now, without waiting for the schedule
stack manage --dir ~/deployments/my-stack backup now

# See what can be restored
stack manage --dir ~/deployments/my-stack backup list

# Restore every volume from the most recent snapshot
stack manage --dir ~/deployments/my-stack backup restore

# Restore a single volume from a specific snapshot
stack manage --dir ~/deployments/my-stack backup restore --snapshot 6478d2ea --volume pgdata

# Fill a new deployment from a dead one's backups
stack manage --dir ~/deployments/my-stack backup restore --from stack-6e0cfa21fe07386d
```

## See Also

- [stack deploy](deploy.md) - Deploy a stack
- [stack init](init.md) - Create a stack specification file
- [backup.md](../backup.md) - Configuring backup, and what it captures
