# Backup &amp; Restore

> **Status: implemented on both targets**, with the parts listed under
> [Not built yet](#not-built-yet) still outstanding. Backups run on a schedule, and
> `stack manage … backup now | list | restore` operate on them.

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
| `backup-s3-bucket`                          | Bucket the repositories are written in.         | —              |
| `backup-s3-key-id`, `backup-s3-key`         | Object store credentials.                       | —              |
| `backup-restic-password`                    | **Encryption key** (see warning below).         | —              |
| `backup-schedule`                           | Cron schedule.                                  | `0 3 * * *`    |
| `backup-prune-schedule`                     | Cron schedule for applying the retention policy.| `0 4 * * 0`    |
| `backup-retention`                          | `forget`/`prune` policy.                        | `--keep-daily 7 --keep-weekly 4 --keep-monthly 6` |

Typical one-time setup for an environment:

```bash
$ stack config set backup true
$ stack config set backup-s3-endpoint https://s3.us-west-2.amazonaws.com
$ stack config set backup-s3-bucket my-stack-backups
$ stack config set backup-s3-key-id AKIA...
$ stack config set backup-s3-key ...
$ stack config set backup-restic-password ...
```

Every setting is required once the master switch is on, the encryption key included: a
deployment that believes it is being backed up and is not is worse than one that is not,
so a Kubernetes deployment with any of them missing fails at `deploy` naming what is
missing, rather than running unbacked.

**Each deployment gets its own restic repository**, named for the deployment inside that
bucket (`<bucket>/<deployment-name>`), on both targets. Beyond keeping deployments'
snapshots from mixing, this is load-bearing on Kubernetes: K8up restores the most recent
snapshot in a repository with no filter for who wrote it, so deployments sharing one could
restore each other's data.

After that, **every** deployment is backed up with no further action:

```bash
$ stack deploy --spec-file ~/specs/todo.yml --deployment-dir ~/deployments/todo
$ stack manage --dir ~/deployments/todo start
# ...the deployment's volumes are now backed up on the configured schedule.
```

> #### ⚠ The encryption key cannot be purely ephemeral
>
> restic cannot decrypt a repository without its password. If `backup-restic-password` is auto-generated and
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
   - mounts every non-excluded volume into the backup container (`- <volume>:/backup/<volume>:rw`,
     read-write so that the same container can restore in place; scheduled backups only read), and
   - injects the ambiently-resolved schedule, retention, object-store and repository settings as
     environment for the container.

3. **The backup container runs restic on a schedule** — on each cron tick it runs any configured
   pre-backup hooks (the logical dumps) and then `restic backup` of the mounted volume tree, applying the
   retention policy.

Because every named volume on the Docker target is already realised as a bind mount under
`<deployment-dir>/data/<volume-name>/`, the set of paths to back up is fully deterministic.

The backup stack is mixed into the deployment by hand, with an extra `--spec-file`, exactly
as the ingress stack is. It is a **Docker-target mix-in only**: on Kubernetes the engine is
the cluster's operator, and a backup container deployed there would sit idle holding no
data mounts, so `deploy` warns if one is mixed into a Kubernetes deployment.

## Kubernetes

On Kubernetes the work is delegated to [K8up](https://k8up.io), a restic-based backup operator. This
follows the same assume-present contract the stack tool already uses for `ingress-nginx` and `cert-manager`
(it references an `ingress_class_name="nginx"` and a `cert-manager.io/cluster-issuer` it does not install):
`stack` does not install K8up; it only emits resources that *reference* it.

- During `stack deploy`, the tool emits, into the deployment's own namespace: a `Secret` holding the
  repository password and the object store credentials, and a K8up `Schedule` naming that Secret, the
  bucket, and the backup and prune schedules. K8up then backs up **every PVC in the namespace**, mounting
  each at `/data/<claim-name>` in its backup job — so what is backed up follows from the deployment, with
  no list to maintain.
- A volume the stack author marked `@stack backup-exclude` gets `k8up.io/backup: "false"` on its PVC, which
  is K8up's own opt-out.
- K8up writes a **standard restic repository**, with the same encryption as the Docker target — so a
  repository written on one target is readable on the other, and with the bare `restic` CLI from outside
  the deployment entirely.
- One thing differs between the targets and is worth knowing before reading a snapshot list: K8up backs
  each volume up as its **own snapshot** (paths `/data/<volume>`), where the Docker target takes one
  snapshot of the whole `/backup` tree.

K8up itself is installed by the **machine provisioning** scripts (`k3s-node.sh` installs it by default,
alongside cert-manager), not by `stack`. A backup-enabled deployment to a cluster without it fails
recognisably at `deploy`, the same way an ingress deployment fails when `cert-manager` is absent; the check
is that K8up's API is registered on the cluster.

> Because the deployment uses a single node (or node affinity to co-locate data), K8up's backup `Job` can
> mount the `ReadWriteOnce` PVCs alongside the running application pod. Cross-node volume access is
> explicitly out of scope.

## Restore

`stack manage … backup restore` restores **in place**, into the deployment's existing volumes:

- **Docker:** `restic restore` in the backup container, which mounts the data volumes read-write for
  exactly this reason.
- **Kubernetes:** a K8up `Restore` per volume, targeting that volume's PVC. K8up trims the `/data/<claim>`
  prefix as it writes, so a volume's files land back at the root of the volume they came from. "Restore the
  latest" is resolved to a specific snapshot id per volume before the resource is created, because K8up's
  own "latest" is the newest snapshot in the repository whatever volume it holds.

**Stopping the deployment first is the operator's job**, and on a live deployment it is the right thing to
do: restoring underneath a running service overwrites files it has open. Orchestrating that — stop,
restore, start — behind the one command is the intended shape and is listed under
[Not built yet](#not-built-yet).

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
| `stack manage --dir <dir> backup now`                          | Run a backup immediately, outside the schedule, and wait for it.   |
| `stack manage --dir <dir> backup list`                         | List the snapshots available to restore.                           |
| `stack manage --dir <dir> backup restore [--snapshot <id>] [--volume <name>]` | Restore in place, defaulting to the latest snapshot and every volume. |

`backup` is a Click sub-group of the existing `manage` group, so it inherits `--dir` and the deployment
context. Internally each subcommand dispatches to the active target: on Docker it `exec`s the backup
container's scripts; on Kubernetes it creates and waits on K8up resources, and reads snapshots from the
`Snapshot` objects K8up syncs into the namespace.

`backup list` prints one line per snapshot — id, time, and the volumes it holds — which is the same on both
targets even though the engines differ:

```
$ stack manage --dir ~/deployments/todo backup list
6478d2ea	2026-08-14T15:10:34Z	app-data,app-data2
```

That last column is where an exclusion shows up: a volume marked `@stack backup-exclude` is visibly absent
from it.

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

## Not built yet

- **Application consistency.** `@stack backup-command` / `@stack backup-file-extension` are parsed no
  further than `backup-exclude` is: `Stack.get_backup_targets` returns an empty `commands` map. Neither the
  Docker target's hook runner nor the Kubernetes `k8up.io/backupcommand` annotation is wired up, so a
  database in a stack is backed up file-level today — see [Application consistency](#application-consistency)
  for why that is not enough for one.
- **`backup restore` does not stop the deployment.** The stop → restore → start orchestration described
  under [Restore](#restore) is the operator's to perform for now.
- **`backup status`, `backup prune` and `backup check`.** Retention is applied on its own schedule; there
  is no command to trigger or inspect it.
- **Auto-including the backup stack.** On the Docker target it is mixed in by hand, with an extra
  `--spec-file`, exactly as the ingress stack is.

Also worth knowing about the Docker engine: a repository created against an object store that is not yet
ready can be written and then never read back (restic reports the init as successful, and every later
attempt fails on "already initialized"). The container detects that and says so rather than looping, but
recovering means removing the repository from the store by hand. A managed object store is always ready;
this is reachable with a store that starts alongside the deployment.
