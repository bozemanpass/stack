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

Standardising on the restic repository format means an operator can always read a repository with the bare
`restic` CLI, from outside the deployment entirely — which is the backstop when anything below does not do
what you need.

The two targets differ in *what runs restic and how it is scheduled*:

| Concern            | Docker                                            | Kubernetes                                   |
| ------------------ | ------------------------------------------------- | -------------------------------------------- |
| Engine / format    | restic (the `bozemanpass/backup` container)       | restic (via **K8up**)                        |
| Scheduling         | cron in the backup container                      | K8up `Schedule` resource                     |
| Quiesce / hooks    | not built (see [Not built yet](#not-built-yet))   | not built                                    |
| Config generation  | `stack` injects config at deploy time             | `stack` emits K8up resources                 |
| Prerequisites      | the backup stack, mixed in with a `--spec-file`   | K8up, installed by the machine provisioning  |
| Restore            | `restic restore` in the backup container          | a K8up `Restore` per volume                  |
| Snapshot layout    | one snapshot per volume, at `/data/<volume>`      | one snapshot per volume, at `/data/<volume>` |

That last row is deliberate rather than coincidental: the Docker target mounts the volumes where K8up
mounts a claim in its own backup job, so both targets record the same paths in a snapshot. **A repository
written by either target can therefore be restored by the other** — a stack developed on compose can be
moved to a cluster carrying its data, and back. It is the same `--from` operation as any other restore
from an existing backup, described under
[Restoring from another deployment's backups](#restoring-from-another-deployments-backups).

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
bucket (`<bucket>/<deployment-name>`), on both targets. That keeps deployments' snapshots
from mixing — two deployments of the same stack have volumes of the same name, so a shared
repository would leave "the latest snapshot of `app-data`" ambiguous between them — and it
makes a deployment's backups identifiable in the bucket by name. Restoring is *not* tied to
that name: any deployment can be filled from any repository, which is what
[`--from`](#restoring-from-another-deployments-backups) is for.

After that, **every** Kubernetes deployment is backed up with no further action:

```bash
$ stack deploy --spec-file ~/specs/todo.yml --deployment-dir ~/deployments/todo
$ stack manage --dir ~/deployments/todo start
# ...the deployment's volumes are now backed up on the configured schedule.
```

On the Docker target the deployment has to carry the engine, so the backup stack is mixed
in with an extra `--spec-file` — the same way the ingress stack is:

```bash
$ stack fetch repo github.com/bozemanpass/backup-stack
$ stack prepare --stack backup
$ stack init --stack backup --output ~/specs/backup.yml

$ stack deploy --spec-file ~/specs/backup.yml \
               --spec-file ~/specs/todo.yml \
               --deployment-dir ~/deployments/todo
$ stack manage --dir ~/deployments/todo start
```

Either way, the first backup happens on the schedule. To prove the arrangement works
without waiting for 03:00:

```bash
$ stack manage --dir ~/deployments/todo backup now
$ stack manage --dir ~/deployments/todo backup list
6478d2ea	2026-08-14T15:10:34Z	uploads
a1b93c07	2026-08-14T15:10:36Z	pgdata
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

By default **every named volume** in a deployment is backed up, file-level; config maps are not. No
annotation or flag is required for this — on Docker it is derived from the merged spec, and on Kubernetes it
is every PVC in the deployment's namespace, which comes to the same set.

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

> ⚠ **This part is not built.** Both annotations are accepted by the parser and go no further — see
> [Not built yet](#not-built-yet). A database in a stack is backed up file-level today, with the torn-file
> risk this section describes. Until it is built, the way to back a database up consistently is to have the
> stack write its own dumps to a volume on a schedule of its own, and let that volume be backed up.

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

Instead the backup service is defined by the mixed-in backup stack, and when the `backup` master switch is
enabled `deploy` **augments** it — precisely parallel to the way it injects `VIRTUAL_HOST_MULTIPORTS`
environment variables into matching services for ingress:

1. **Annotations to spec** — during `stack init`, any `@stack backup-*` annotations are parsed out of
   `composefile.yml` into a `backup` section of the output spec.

2. **Spec to backup container** — during `stack deploy`, the tool reads the merged deployment's volumes
   (`Spec.get_volumes()`) and:
   - mounts every non-excluded volume into the backup container (`- <volume>:/data/<volume>:rw`,
     read-write so that the same container can restore in place; scheduled backups only read), and
   - injects the ambiently-resolved schedule, retention, object-store and repository settings as
     environment for the container.

3. **The backup container runs restic on a schedule** — on each cron tick it runs `restic backup` of the
   mounted volume tree and applies the retention policy. (The pre-backup hooks that would run the logical
   dumps are scaffolded in the image but never configured; see
   [Application consistency](#application-consistency).)

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
- K8up backs each volume up as its **own snapshot**, recorded at `/data/<volume>`. The Docker target does
  the same, which is what makes the repositories interchangeable (see [Engine: restic](#engine-restic)).

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
- **Kubernetes:** a K8up `Restore` per volume, targeting that volume's PVC, with `paths` narrowed to that
  volume so K8up takes the newest snapshot *of it* rather than the newest in the repository. K8up trims the
  `/data/<claim>` prefix as it writes, so a volume's files land back at the root of the volume they came
  from.

**Stopping the deployment first is the operator's job**, and on a live deployment it is the right thing to
do: restoring underneath a running service overwrites files it has open. Orchestrating that — stop,
restore, start — behind the one command is the intended shape and is listed under
[Not built yet](#not-built-yet).

### Restoring from another deployment's backups

A deployment backs up to a repository named after itself, so its backups are identifiable and cannot
collide with anyone else's. Restoring is not tied to that: `--from` names the deployment whose backups to
read, and changes nothing else — the deployment keeps its own identity and goes on backing up to its own
repository.

The deployment being restored *into* needs no special treatment: deploy it normally, start it, and restore.

#### Disaster recovery: the cluster is gone

You need three things to have survived it — the repository password, the object store credentials, and the
name of the dead deployment. That name is its directory in the bucket, so it can be recovered from there if
the deployment directory went down with the cluster:

```bash
$ restic -r s3:https://nyc3.digitaloceanspaces.com/my-stack-backups list keys   # any repo, to check credentials
$ aws s3 ls s3://my-stack-backups/                                              # ...or just look
                           PRE stack-6e0cfa21fe07386d/
```

Then deploy the stack again — on the new cluster, under its own new name — and fill it:

```bash
$ stack deploy --spec-file ~/specs/todo.yml --deployment-dir ~/deployments/todo
$ stack manage --dir ~/deployments/todo start
$ stack manage --dir ~/deployments/todo backup restore --from stack-6e0cfa21fe07386d
```

The new deployment now holds the old one's data and backs up to a repository of its own. The old
repository is left untouched, so a second attempt costs nothing.

#### Fan-out: many copies of one dataset

A stack that has built up expensive state — a scraped index, say — can be copied to as many deployments as
you like, each seeded from one backup. Take a backup of the source, then seed each copy from it:

```bash
$ stack manage --dir ~/deployments/indexer backup now
$ source_name=$( grep '^cluster-id:' ~/deployments/indexer/deployment.yml | awk '{print $2}' )

$ for region in nyc3 fra1 sgp1; do
    stack deploy --spec-file ~/specs/indexer-${region}.yml --deployment-dir ~/deployments/indexer-${region}
    stack manage --dir ~/deployments/indexer-${region} start
    stack manage --dir ~/deployments/indexer-${region} backup restore --from "$source_name"
  done
```

Each copy has its own identity and its own schedule from then on, and none of them can disturb the source
or each other. Two things to size up first: each copy is a **full** copy in the object store, since restic
deduplicates within a repository and not across them; and every copy is seeded from the same instant, so
whatever the source had not yet written at backup time is missing from all of them equally.

#### What gets filled

Which volumes are filled comes from the deployment doing the restoring, not from the backup: the request is
"fill my volumes from that backup". A volume the backup does not hold is reported and skipped rather than
abandoning the restore half-done — unless you named it with `--volume`, in which case its absence is the
answer to what you asked.

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
| `stack manage --dir <dir> backup restore [--snapshot <id>] [--volume <name>] [--from <deployment>]` | Restore in place, defaulting to the latest snapshot and every volume. `--from` reads another deployment's backups. |

`backup` is a Click sub-group of the existing `manage` group, so it inherits `--dir` and the deployment
context. Internally each subcommand dispatches to the active target: on Docker it `exec`s the backup
container's scripts; on Kubernetes it creates and waits on K8up resources, and reads snapshots from the
`Snapshot` objects K8up syncs into the namespace.

`backup list` prints one line per snapshot — id, time, and the volumes it holds — which is the same on both
targets even though the engines differ:

```
$ stack manage --dir ~/deployments/todo backup list
6478d2ea	2026-08-14T15:10:34Z	uploads
a1b93c07	2026-08-14T15:10:36Z	pgdata
```

Each volume is backed up as its own snapshot, on both targets, so the last column normally holds one name.
It is where an exclusion shows up: a volume marked `@stack backup-exclude` never appears.

> The earlier sketch of `stack deploy backup status` is intentionally **not** the chosen shape: `deploy`
> creates a deployment from specs and exits, whereas backup status/restore/list are operations *on an
> existing* deployment — which is precisely what `manage` is for.

## Open questions

- **Auto-enable vs explicit switch.** This design gates backup on an explicit `backup` master switch
  (profile setting / `STACK_BACKUP`) so behaviour is predictable. The most transparent alternative —
  enabling backup automatically whenever a destination is configured — is rejected as too implicit, but is
  worth revisiting.
- **Encryption-key escrow.** `backup-restic-password` must be set by the operator today — nothing
  auto-generates it, which is the safe half of the problem. What is unsettled is whether the tool should
  help persist and surface it at all (see the warning above).
- **Monitoring.** Surfacing backup success/failure (a healthcheck or status that `backup status` can read)
  so that a silently failing backup is not mistaken for a working one. `backup now` reports its own result,
  but a *scheduled* backup that fails is currently visible only in the engine's logs.
- **Moving a deployment between targets.** The repositories are interchangeable, so the data can move; what
  is untested is everything else about running the same stack on the other target.

## Not built yet

- **Application consistency — the significant one.** `@stack backup-command` /
  `@stack backup-file-extension` are parsed no further than `backup-exclude` is:
  `Stack.get_backup_targets` returns an empty `commands` map. Neither the Docker target's hook runner nor
  the Kubernetes `k8up.io/backupcommand` annotation is wired up, so a database in a stack is backed up
  file-level today — see [Application consistency](#application-consistency) for why that is not enough
  for one.
- **`backup restore` does not stop the deployment.** The stop → restore → start orchestration described
  under [Restore](#restore) is the operator's to perform for now.
- **`backup status`, `backup prune` and `backup check`.** Retention is applied on its own schedule; there
  is no command to trigger or inspect it.
- **`backup list` only reads the deployment's own repository.** On Kubernetes it reads the `Snapshot`
  objects K8up syncs into the namespace, which describe that repository alone, so there is no
  `backup list --from`. Restoring from elsewhere does not need it — the latest snapshot per volume is
  chosen by K8up — but naming a specific `--snapshot` in someone else's repository means finding the id
  another way.
- **An end-to-end disaster-recovery test.** The backup test restores within one deployment, and seeds a
  second deployment from the first, both on one cluster. The real exercise — back up, destroy the cluster,
  provision a new one, restore into a fresh deployment, and check the data — spans two CI jobs that have to
  agree on what was written, and is not built.
- **Cross-target restore is not covered by a test.** Both directions were verified by hand when the layouts
  were aligned (a compose-written repository restored on a real cluster, and a K8up-written one restored on
  compose), but nothing re-checks it: a test would need a compose deployment writing to a real object store
  *and* a cluster in the same run. It is the same two-job shape as the recovery test above.
- **Auto-including the backup stack.** On the Docker target it is mixed in by hand, with an extra
  `--spec-file`, exactly as the ingress stack is.

Also worth knowing about the Docker engine: a repository created against an object store that is not yet
ready can be written and then never read back (restic reports the init as successful, and every later
attempt fails on "already initialized"). The container detects that and says so rather than looping, but
recovering means removing the repository from the store by hand. A managed object store is always ready;
this is reachable with a store that starts alongside the deployment.
