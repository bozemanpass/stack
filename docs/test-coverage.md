# Where is it tested?

A cross-reference from commands and functional areas to the test code that
exercises them.  The integration tests double as working examples: each one is
a real, end-to-end use of the commands it names, so this page is also a map to
runnable documentation.

Entries name a **step** rather than a line number: the quoted string appears
verbatim in the test script (search for it in the file, or for
`<step>: passed` in a CI log), and unlike a line number it does not silently
go stale when the script is edited.  A unit test
(`tests/unit/test_coverage_doc.py`) checks every file and step named here
against the tree, so this page fails `uv run pytest` rather than rotting.

Which targets a test *supports* is a property of the script (see
`select_deploy_target` in `tests/lib/common.sh`); which combinations CI
*runs*, and how often, is decided by cost and noted per entry.  "weekly"
means the run provisions a real cloud VM and is never triggered per-PR;
those workflows also run on manual dispatch.

The pytest suite in [`tests/unit/`](../tests/unit/) is not indexed row-by-row
here: it runs the CLI in a subprocess with an isolated `HOME` and no
Docker or Kubernetes, and its files are named by subject
(`test_init_volumes.py`, `test_secrets.py`, `test_k8s_logs.py`, ...), so the
file listing is its own index.

## Build and prepare

| What | Test | Step | CI runs |
|---|---|---|---|
| `fetch repo`, `prepare`, `build containers` | [`tests/smoke-test/run-smoke-test.sh`](../tests/smoke-test/run-smoke-test.sh) | whole script | compose, per-PR |
| Rebuild giving a dirty checkout a `stackdev-` identity | [`tests/app-deploy/run-test.sh`](../tests/app-deploy/run-test.sh) | `deploy update content` | compose + kind per-PR; remote + remote-compose weekly |
| `webapp` wrapper (build and serve a Vite/React app) | [`tests/webapp-test/run-webapp-test.sh`](../tests/webapp-test/run-webapp-test.sh) | whole script | compose, per-PR and weekly |
| `static-content` wrapper | [`tests/static-content-test/run-static-content-test.sh`](../tests/static-content-test/run-static-content-test.sh) | whole script | compose, per-PR and weekly |

## Init and deploy

| What | Test | Step | CI runs |
|---|---|---|---|
| `init` spec generation | [`tests/app-deploy/run-test.sh`](../tests/app-deploy/run-test.sh) | `deploy init test` | compose + kind per-PR; remote + remote-compose weekly |
| `deploy` deployment-directory creation | [`tests/app-deploy/run-test.sh`](../tests/app-deploy/run-test.sh) | `deploy create test` | compose + kind per-PR; remote + remote-compose weekly |
| Stack deploy hooks (`init`, `create`) | [`tests/smoke-test/run-smoke-test.sh`](../tests/smoke-test/run-smoke-test.sh) | `deploy init hook`, `deploy create hook` | compose, per-PR |
| The agent-skill quickstart path (project-local stack, generated secrets) | [`tests/skill/run-skill-test.sh`](../tests/skill/run-skill-test.sh) | `skill test validate`, `skill test build`, `skill test deploy`, `skill test secrets`, `skill test http` | compose, per-PR |

## Manage: lifecycle and data

| What | Test | Step | CI runs |
|---|---|---|---|
| `manage start` / `stop`, HTTP service reachability | [`tests/app-deploy/run-test.sh`](../tests/app-deploy/run-test.sh) | `deploy http` | compose + kind per-PR; remote + remote-compose weekly |
| Data survives `stop`/`start` (volumes per target) | [`tests/app-deploy/run-test.sh`](../tests/app-deploy/run-test.sh) | `deploy storage` | compose + kind per-PR; remote + remote-compose weekly |
| Volume persistence with a database workload | [`tests/database/run-test.sh`](../tests/database/run-test.sh) | `Create database content test`, `Retain database content test` | compose + kind per-PR; remote weekly |
| `manage update`: config change reaches the containers | [`tests/app-deploy/run-test.sh`](../tests/app-deploy/run-test.sh) | `deploy update config` | compose + kind per-PR; remote + remote-compose weekly |
| `manage update`: data survives the in-place update | [`tests/app-deploy/run-test.sh`](../tests/app-deploy/run-test.sh) | `deploy update storage` | compose + kind per-PR; remote + remote-compose weekly |
| `manage update`: rebuilt image content reaches the deployment | [`tests/app-deploy/run-test.sh`](../tests/app-deploy/run-test.sh) | `deploy update content` | compose + kind per-PR; remote + remote-compose weekly |
| Spec-mapped volume path: pre-existing host data reaches the container | [`tests/volumes/run-test.sh`](../tests/volumes/run-test.sh) | `external data visible test`, `unmapped volume fresh test`, `volume write-back test` | compose + kind per-PR; remote weekly |
| `manage exec` against a running service | [`tests/database/run-backup-test.sh`](../tests/database/run-backup-test.sh) | `Replay dump test` | compose per-PR; remote weekly |

## Backup and restore

| What | Test | Step | CI runs |
|---|---|---|---|
| `manage backup now` / `list` / `restore` (the file path) | [`tests/backup/run-test.sh`](../tests/backup/run-test.sh) | `Backup test`, `Restore content test` | compose per-PR; remote weekly |
| `@stack backup-command` dump capture | [`tests/backup/run-test.sh`](../tests/backup/run-test.sh) | `Dump content test` | compose per-PR; remote weekly |
| Full recovery: destroy the deployment, rebuild from the dump | [`tests/database/run-backup-test.sh`](../tests/database/run-backup-test.sh) | `Destroy deployment test`, `Replay dump test`, `Restore database content test` | compose per-PR; remote weekly |

## Kubernetes specifics

| What | Test | Step | CI runs |
|---|---|---|---|
| Node affinity and toleration spec controls | [`tests/k8s-deployment-control/run-test.sh`](../tests/k8s-deployment-control/run-test.sh) | `deployment of pod test`, `pod placement test` | kind only (builds its own multi-node cluster), per-PR |
| `runtime-class`: a sandboxed (kata) pod runs its own kernel, its neighbour does not | [`tests/kata/run-test.sh`](../tests/kata/run-test.sh) | `kata isolation test`, `unsandboxed pod control test` | remote only (needs a cluster provisioned with kata), weekly |
| Volume bound to a node path (`local` PV with volume affinity) | [`tests/volumes/run-test.sh`](../tests/volumes/run-test.sh) | `external data visible test` on the remote target (see [`tests/k3s-deploy/`](../tests/k3s-deploy/)) | weekly |
| HTTPS ingress on Docker (`docker-ingress` mix-in, real certificates) | [`tests/app-deploy/run-test.sh`](../tests/app-deploy/run-test.sh) | `deploy http` on the remote-compose target (see [`tests/docker-deploy/`](../tests/docker-deploy/)) | weekly |
| Gateway API HTTP routing on a real cluster | [`tests/app-deploy/run-test.sh`](../tests/app-deploy/run-test.sh) | `deploy http` on the remote target (see [`tests/k3s-deploy/`](../tests/k3s-deploy/)) | weekly |
