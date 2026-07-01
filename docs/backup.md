# Backup &amp; Restore

> **Status: design proposal — not yet implemented.** This document describes the intended design for
> backing up and restoring service data. It is written to be reviewed and refined before any code is
> written. Where it describes commands or behaviour, read those as *proposed*.

Stacks keep their software components and configuration under revision control in git. Once a stack is
running, however, it accumulates **persistent data** in mounted volumes that git does not track. This
document describes how that data is backed up to object storage (S3) and restored from a previous epoch.

## Design goal: "backup my stuff", and nothing more

The feature is designed to be as transparent as possible. In the common case the person deploying a stack
provides **no backup-specific information at all** — not which volumes to back up, not where to send them,
not on what schedule. Backup is configured once at the environment/profile level and then applies to every
deployment automatically.

This is achieved by deriving everything possible from what the stack tool already knows or can source
ambiently:

- **What to back up** is derived from the deployment itself: *all* read-write named volumes are backed up
  by default. The tool already enumerates them (`Spec.get_volumes()`).
- **Where to back up, with which credentials, on what schedule** is sourced from the environment using the
  existing configuration precedence (see [Configuration](#configuration)).

Annotations exist only to *refine* this default, and are written by the **author** of a stack, never by
the person deploying it.

## Engine: restic

All backups — on both targets — are stored as a [restic](https://restic.net) repository. restic is the
contract, not an implementation detail:

- **Client-side encryption is mandatory** (AES-256). The payload is encrypted *before* upload, so the
  object store never sees plaintext. This is what makes backing up to commodity object storage acceptable.
- **Content-addressed dedup + incremental snapshots.** A daily backup of a mostly-static volume costs
  almost nothing.
- **Snapshots and retention policies** give point-in-time restore (your "previous epoch").
- **Native S3 backend** (and any S3-compatible store: MinIO, Wasabi, etc.).

Standardising on the restic repository format means a backup written on the Docker target is restorable on
the Kubernetes target and vice-versa, and that in a pinch an operator can restore with the bare `restic`
CLI from outside the deployment entirely.

The two targets differ only in *what runs restic and how it is scheduled*:

| Concern            | Docker                                            | Kubernetes                                   |
| ------------------ | ------------------------------------------------- | -------------------------------------------- |
| Engine / format    | restic (off-the-shelf restic container image)     | restic (via **K8up**)                        |
| Scheduling         | cron in the backup container                      | K8up `Schedule` resource                     |
| Quiesce / hooks    | pre/post hooks in the backup container            | `k8up.io/backupcommand` pod annotation       |
| Config generation  | `stack` injects config at deploy time             | `stack` emits K8up resources                 |
| Prerequisites      | the auto-injected backup container                | the `cluster` tool ensures K8up is present   |
| Restore            | start-stripped → restic restore → start full      | K8up `Restore` into freshly-created PVCs     |

## Configuration

Backup settings are resolved with the standard stack configuration precedence
(`config/util.py:get_config_setting`): **environment variable → active profile → built-in default**. This
is what lets backup be ambient — set it once in a profile and every deployment under that profile inherits
it, with no per-stack input.

| Setting (profile key / `STACK_…` env var)   | Purpose                                         | Default        |
| ------------------------------------------- | ----------------------------------------------- | -------------- |
| `backup` / `STACK_BACKUP`                   | Master switch — enable backup for deployments.  | `false`        |
| `backup-s3-endpoint`                        | Object store endpoint.                          | —              |
| `backup-s3-bucket`                          | Bucket / repository location.                   | —              |
| `aws-access-key-id`, `aws-secret-access-key`| Object store credentials.                       | —              |
| `restic-password`                           | **Encryption key** (see warning below).         | —              |
| `backup-schedule`                           | Cron schedule.                                  | `0 3 * * *`    |
| `backup-retention`                          | `forget`/`prune` policy.                        | `--keep-daily 7 --keep-weekly 4 --keep-monthly 6` |

Typical one-time setup for an environment:

```bash
$ stack config set backup true
$ stack config set backup-s3-endpoint s3.us-west-2.amazonaws.com
$ stack config set backup-s3-bucket my-stack-backups
$ stack config set aws-access-key-id AKIA...
$ stack config set aws-secret-access-key ...
$ stack config set restic-password ...
```

After that, **every** deployment is backed up with no further action:

```bash
$ stack deploy --spec-file ~/specs/todo.yml --deployment-dir ~/deployments/todo
$ stack manage --dir ~/deployments/todo start
# ...the deployment's volumes are now backed up on the configured schedule.
```

> #### ⚠ The encryption key cannot be purely ephemeral
>
> restic cannot decrypt a repository without its password. If `restic-password` is auto-generated and
> lives *only* in an environment that is later lost, the backups become **permanently unrecoverable** — an
> encrypted bucket that can never be read. The password must therefore either be set explicitly by the
> operator, or be auto-generated **and persisted and surfaced for the operator to escrow**. This is the one
> piece of backup configuration that must not be treated as disposable ambient state. Object-store
> credentials, by contrast, can be rotated freely.

## Volume selection (automatic)

By default **all read-write named volumes** in a deployment are backed up, file-level. Read-only mounts and
config maps are skipped. No annotation or flag is required for this — it is derived entirely from the
merged spec.

The only optional refinement is to *exclude* a volume that is a cache, scratch space, or otherwise cheaply
reconstructable, using an annotation in the stack's `composefile.yml`:

```yaml
services:
  backend:
    image: bozemanpass/todo-backend:stack
    volumes:
      - "uploads:/app/uploads"              # backed up by default
      - "cache:/app/cache"                  # @stack backup-exclude
```

Excluding a volume is an **author** decision encoded in the component, not something the deployer supplies.

## Application consistency

This is the one place where "just back up everything" needs care, and it is worth stating plainly: the
ingress analogy is misleading because ingress is *stateless* whereas backup is *deeply stateful*. A
file-level copy of a **live database's** data directory, read file-by-file while the database writes, can
produce a torn, unrestorable snapshot.

For such services the stack author adds a single annotation specifying a logical dump command, whose stdout
is captured into the backup instead of (or alongside) the raw files:

```yaml
services:
  db:
    image: bozemanpass/todo-db:stack
    volumes:
      - "pgdata:/var/lib/postgresql/data"   # @stack backup-exclude
    # @stack backup-command pg_dump -U postgres -d todos
    # @stack backup-file-extension sql
```

Crucially this is **author-time** metadata: whoever packages the database component writes it once, and
every deployer of that stack gets consistent backups for free, having supplied nothing. The annotation maps
one-to-one onto K8up's `k8up.io/backupcommand` / `k8up.io/file-extension` pod annotations on the Kubernetes
target, and onto a pre-backup hook in the restic container on the Docker target.

### Annotation summary

There are only two optional annotations, both author-time, both with safe "just back it up" defaults:

| Annotation                          | Applies to     | Meaning                                                                 |
| ----------------------------------- | -------------- | ----------------------------------------------------------------------- |
| `@stack backup-exclude`             | a volume mount | Do not include this volume in the file-level backup.                    |
| `@stack backup-command <cmd>`       | a service      | Capture `<cmd>`'s stdout into the backup (e.g. a consistent DB dump).   |
| `@stack backup-file-extension <ext>`| a service      | Name the captured `backup-command` output with this extension.         |

A stack that uses none of these is still fully backed up — every read-write volume, file-level.

## How Docker backup works

Like ingress, the stack tool does **not** write the backup engine's job logic by hand. It generates
configuration for an existing restic container image and lets that image do the work. The backup container
cannot be a purely *static* mix-in, because at the time its image is built it does not know which volumes
the application stack will contribute — and naming them statically would collide with the merge step, which
requires unique volume names across mixed-in specs.

Instead, when the `backup` master switch is enabled, the backup container is **injected at deploy time**,
precisely parallel to the way `deploy` injects `VIRTUAL_HOST_MULTIPORTS` environment variables into
matching services for ingress:

1. **Annotations to spec** — during `stack init`, any `@stack backup-*` annotations are parsed out of
   `composefile.yml` into a `backup` section of the output spec.

2. **Spec to backup container** — during `stack deploy`, the tool reads the merged deployment's volumes
   (`Spec.get_volumes()`) and:
   - mounts every non-excluded read-write volume **read-only** into the backup container
     (`- <volume>:/backup/<volume>:ro`), and
   - injects the ambiently-resolved schedule, retention, object-store, and per-service `backup-command`
     hook settings as environment / config for the container.

3. **The backup container runs restic on a schedule** — on each cron tick it runs any configured
   pre-backup hooks (the logical dumps) and then `restic backup` of the mounted volume tree, applying the
   retention policy.

Because every named volume on the Docker target is already realised as a bind mount under
`<deployment-dir>/data/<volume-name>/`, the set of paths to back up is fully deterministic.

## Kubernetes

On Kubernetes the work is delegated to [K8up](https://k8up.io), a restic-based backup operator. This
follows the same assume-present contract the stack tool already uses for `ingress-nginx` and `cert-manager`
(it references an `ingress_class_name="nginx"` and a `cert-manager.io/cluster-issuer` it does not install):
`stack` does not install K8up; it only emits resources that *reference* it.

- During `stack deploy`, the tool emits a K8up `Schedule` for the deployment's namespace (one namespace per
  deployment), so all of its PVCs are backed up, together with `k8up.io/backupcommand` /
  `k8up.io/file-extension` annotations derived from the `@stack backup-*` annotations.
- K8up writes a **standard restic repository** to the same object store, with the same encryption — so the
  repositories are interchangeable with those produced on the Docker target.

K8up itself is provisioned by the **`cluster`** tool (the batteries-included checker/fixer for required
cluster components), exactly as `cluster` is responsible for `cert-manager` and `ingress-nginx`. A
backup-enabled deployment fails recognisably — the same way an ingress deployment fails today when
`cert-manager` is absent — if K8up has not been provisioned. The readiness probe is concrete: K8up's CRDs
registered and its operator `Deployment` healthy.

> Because the deployment uses a single node (or node affinity to co-locate data), K8up's backup `Job` can
> mount the `ReadWriteOnce` PVCs alongside the running application pod. Cross-node volume access is
> explicitly out of scope.

## Restore

Restore is deliberately modelled as a distinct mode rather than a live operation, which neatly sidesteps the
problem of two consumers mounting the same volume at once. At restore time **nothing else holds the
volumes**, so even `ReadWriteOnce` PVCs can be attached by the restore job.

The flow:

1. The full stack is stopped (if running).
2. The volumes are (re)created empty.
3. A **backup-only** variant of the deployment is brought up, running a restore of the chosen snapshot:
   - **Docker:** bring up only the backup container with a restore command, restoring into the now-empty
     bind-mounted volumes.
   - **Kubernetes:** create a K8up `Restore` resource targeting the freshly-created PVCs.
4. The backup-only variant is torn down once the restore completes.
5. The full stack is started; its volumes now contain the restored data.

This is driven by a single command (see below) so the operator does not orchestrate the steps by hand.

## Command structure

Backup *configuration* is ambient (above) and backup runs automatically. The commands below are for
*operating on* an existing deployment — inspecting, triggering off-schedule, and restoring — so they live
under `stack manage --dir <dir>`, alongside `start`, `stop`, `ps`, and `logs`. They are **not** under
`stack deploy`, which only *creates* a deployment and exits.

```
stack manage --dir <dir> backup <subcommand>
```

| Command                                                        | Description                                                        |
| -------------------------------------------------------------- | ------------------------------------------------------------------ |
| `stack manage --dir <dir> backup now`                          | Run a backup immediately, outside the schedule.                    |
| `stack manage --dir <dir> backup status`                       | Show the result of the last run and repository health.             |
| `stack manage --dir <dir> backup list`                         | List snapshots (the available epochs) with timestamps and tags.    |
| `stack manage --dir <dir> backup restore [--snapshot <id>]`    | Orchestrate the full stop → restore → restart flow. Defaults to the latest snapshot; `--volume <name>` restores a single volume; `--and-start` restarts the full stack on completion. |
| `stack manage --dir <dir> backup prune`                        | Apply the retention policy (`forget` + `prune`).                   |
| `stack manage --dir <dir> backup check`                        | Verify repository integrity.                                       |

`backup` is a Click sub-group of the existing `manage` group, so it inherits `--dir` and the deployment
context. Internally each subcommand dispatches to the active target: on Docker it `exec`s restic in the
backup container (or runs a one-off restore deployment); on Kubernetes it creates/reads the corresponding
K8up resources.

> The earlier sketch of `stack deploy backup status` is intentionally **not** the chosen shape: `deploy`
> creates a deployment from specs and exits, whereas backup status/restore/list are operations *on an
> existing* deployment — which is precisely what `manage` is for.

## Open questions

- **Auto-enable vs explicit switch.** This design gates backup on an explicit `backup` master switch
  (profile setting / `STACK_BACKUP`) so behaviour is predictable. The most transparent alternative —
  enabling backup automatically whenever a destination is configured — is rejected as too implicit, but is
  worth revisiting.
- **Encryption-key escrow.** The concrete mechanism for persisting and surfacing an auto-generated
  `restic-password` so it cannot be silently lost (see the warning above).
- **Off-the-shelf Docker image.** Candidates that preserve the restic-repo format include `mazzolino/restic`
  and `lobaro/restic-backup-docker`. (`offen/docker-volume-backup` is feature-rich but defaults to
  tar+GPG, which would break cross-target compatibility.)
- **Monitoring.** Surfacing backup success/failure (a healthcheck or status that `backup status` can read)

  so that a silently failing backup is not mistaken for a working one.
- **New repository.** The Docker backup container lives in its own repo (e.g. `bozemanpass/backup-stack`),
  mirroring `bozemanpass/docker-ingress-stack`.
