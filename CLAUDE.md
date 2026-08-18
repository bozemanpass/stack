# CLAUDE.md

## Project Overview

BPI Stack is a Python CLI tool for building, deploying, and managing software "stacks" — groups of containers defined in a component model similar to Docker Compose. It abstracts over Docker Compose and Kubernetes, allowing transparent deployment to either target.

**Repository:** https://github.com/bozemanpass/stack
**License:** AGPL-3.0

## Quick Reference

- **Language:** Python 3.10+
- **CLI framework:** Click
- **Entry point:** `src/stack/main.py` → `cli` group
- **Package name:** `stack` (invoked as `stack` on the command line)
- **Version:** defined in `pyproject.toml`

## Development Setup

```bash
# Install dependencies (creates .venv via uv)
./scripts/developer-mode-setup.sh

# Run the CLI in dev mode
uv run stack

# Build a distributable zipapp
./scripts/build_shiv_package.sh
```

## Linting

```bash
uv run flake8 --config tox.ini
```

Linting config is in `tox.ini`; `./scripts/lint.sh` runs what CI runs.

There is no autoformatter, deliberately. `max-line-length` is a ceiling, not a target: code
wrapped shorter than it is wrapped that way on purpose, and a formatter that joins those
lines back up to the limit is not wanted here. Match the wrapping of the surrounding code
by hand.

## Testing

Unit tests (pytest) live in `tests/unit/` and run the CLI in a subprocess with an isolated `HOME`, no Docker or Kubernetes required:

```bash
uv run pytest
```

The integration tests are **bash shell scripts**, not pytest. They require Docker and/or Kubernetes (Kind) to be available.

```bash
# Smoke tests (basic CLI functionality)
./tests/smoke-test/run-smoke-test.sh

# App deployment test (Docker by default)
./tests/app-deploy/run-test.sh

# Volume persistence test, against a local kind cluster
STACK_TEST_TARGET=kind ./tests/database/run-test.sh

# K8s pod placement controls (kind only — builds its own multi-node cluster)
./tests/k8s-deployment-control/run-test.sh

# App deployment over HTTPS on a real cloud machine running docker.
# Provisions and destroys a VM, so it costs money; see tests/docker-deploy.
./tests/docker-deploy/with-docker-machine.sh ./tests/app-deploy/run-test.sh
```

There are four deployment targets, and a test that works against more than one
calls `select_deploy_target` (in `tests/lib/common.sh`) and is pointed at one
with `STACK_TEST_TARGET`: `compose` (the default), `kind`, `remote` (a real k8s
cluster) or `remote-compose` (Docker Compose on a real cloud machine). Tests
that are only about general behaviour stay on compose; the ones likely to find
target-specific bugs — currently `app-deploy`, `database` and `volumes` — are
written to run on more than one. Anything genuinely target-shaped belongs in
`select_deploy_target` rather than in an `if` inside a test.

Target-shaped is not the same as engine-shaped, and the two used to be conflated
here. `app-deploy` asked whether the target was `compose` to decide whether each
service was reached on a host port of its own or behind one hostname — which was
right for as long as compose meant a laptop, and wrong the moment a compose
deployment got a real hostname. It asks `TEST_HTTP_ROUTING` now.

`tests/database` holds two scripts. `run-test.sh` is the volume-persistence test
described above. `run-backup-test.sh` makes the same assertion across a wider
gap — back the loaded stack up, destroy the deployment, and rebuild the database
in a new one — and is a second script rather than a step of the first so that the
first goes on depending on nothing but the stack it deploys. They run in the same
CI job, since the second reuses the first's stack and images.

What that second test covers that the `backup` test does not is the **dump** path:
the database stack excludes its data directory and streams a `pg_dump` at backup
time instead, so the repository holds no database files at all and recovery means
reading the dump snapshot back out with the bare `restic` CLI and replaying it
with `psql`. That external route is deliberate — `backup restore` fills volumes
and a dump is not a volume — and it is also the only recovery route that is the
same on both targets, since a cluster has no backup container to read a dump out
of. The `backup` test covers the file path. It runs on `compose` and `remote`,
per-PR only on compose with the remote leg weekly. No kind leg: kind has no K8up.

A word on why the dump is streamed rather than written to a file in a volume, since
the latter looks more convenient and was tried first: a "backup command" means the
command's **stdout is the backup**, on both engines. It is not a quiesce hook that
prepares files for the volume backup, and K8up in particular snapshots the PVCs
independently of the annotated command — measured on a real cluster taking the PVC
snapshot eight seconds *before* running the command. A dump written into a volume
is therefore captured a backup late there, or never, which looks exactly like a
working backup until you need it.

Its assertion is a **row written by the run itself**, not the test client's
"data already exists" report, and that is load-bearing rather than incidental. The
new deployment's client comes up and creates the stack's test data for itself, so
"the data is there" is true before anything is restored; only a row that could
have come from nowhere but the backup tells a working restore from a no-op. It is
also what makes one script serve both targets — the alternative was to keep the
client from ever running, and on Kubernetes there is no way to do that (`up()`
ignores its service list, and the PVCs only exist once the deployment starts).

`backup` runs on `compose` and `remote` but not `kind`, and the reason is the
backup engine rather than the test: on a cluster, backups are run by K8up, which
the machine provisioning installs and a kind cluster does not have. Its
per-target divergence (which object store, and whether the backup stack has to be
mixed in) lives in `select_backup_target`, next to `select_deploy_target`.

A test can also be legitimately single-target: `k8s-deployment-control` appends
labelled and tainted worker nodes to the deployment's kind config, so it only
works where the test owns the cluster. It still goes through
`select_deploy_target` for the init plumbing, and refuses a `STACK_TEST_TARGET`
other than `kind` rather than silently testing nothing.

Which combinations CI actually runs is a separate question from which ones a
test supports, and is decided by cost: `app-deploy`, `database` and `volumes`
run on compose and kind per-PR, and on remote weekly. `backup` runs on compose
per-PR and on remote weekly. `app-deploy` also runs on `remote-compose` weekly,
and it is the only test that does. The remote leg of `volumes` is the one place
the node-path volume mechanism (a `local` PersistentVolume with node affinity —
see `docs/volumes.md`) runs for real: it seeds a directory on the cluster's
node over SSH, using the command `cluster.sh provision` publishes as
`STACK_TEST_NODE_SSH_COMMAND`, and the compose and kind legs cover the same
spec edit's bind-mount meaning.

Compose is worth keeping in that set for a reason beyond docker coverage: it is
the only target that does not restart a failed container, so a service that only
ever comes up because something restarted it fails there and passes on k8s.

The `remote` target needs a real cluster, which costs money and minutes, so it
is never triggered per-PR. `tests/k3s-deploy/with-k3s-cluster.sh` provisions one
on a cloud VM and runs the test scripts named on its command line against it,
sharing the one cluster; the "Real K8S Deploy Test" workflow runs it weekly and
on manual dispatch.

That wrapper is for a person at a terminal. The lifecycle underneath it is
`tests/k3s-deploy/cluster.sh provision|diagnostics|destroy`, keeping the cluster
in a state directory between commands, and CI drives those directly so that each
test is a GitHub Actions step of its own: sharing the VM should not mean sharing
one pass/fail across four tests, which left "which test failed?" answerable only
by reading the log. Adding a remote test therefore means adding both a name to
the plan job's per-leg list and a step that runs it. The step's `if` matches that
name, and the `tests` dispatch dropdown offers the same names.

Teardown is the price of that arrangement: an exit trap covered every way the
old single script could end, and a workflow step does not, so the destroy step is
`if: always()` and every step that could hang carries a `timeout-minutes` — a
job that hits the *job* timeout skips its remaining steps and leaves the VM
running.

`remote-compose` is the same arrangement for Docker: `tests/docker-deploy/`
holds `machine.sh provision|sync|run|diagnostics|destroy` and a
`with-docker-machine.sh` wrapper, and the "Remote Docker Deploy Test" workflow
runs the app deploy test on a real VM weekly and on manual dispatch. Two
differences from the cluster harness are worth knowing before touching it:

- **The test runs on the VM**, which is why `machine.sh` has a `run` command and
  `cluster.sh` does not. A remote cluster is driven over its API from wherever
  the test runs; Docker has no such thing, and the compose deployer writes the
  deployment's files and bind-mounts its volume directories wherever the daemon
  is. So provisioning uploads `tests/` and `package/` and `run` invokes the test
  over SSH. The images are built there too — the app's repository is public —
  and no registry is involved.
- **Only `app-deploy` runs there**, because TLS is the only thing about the
  Docker target that a laptop cannot cover: it needs a public address, a name in
  public DNS a CA can resolve, and ports 80 and 443. Backups and volumes are the
  same code locally and are covered per-PR on compose. Resist adding tests to
  this job on the grounds that the VM is already paid for; that argument holds
  for the cluster, whose *behaviour* differs, and not here.

TLS on Docker is served by the `docker-ingress` stack (nginx-proxy plus
acme-companion) mixed into the deployment, which `init_ingress_mix_in` prepares
— see `docs/ingress.md`. It uses the Let's Encrypt production CA rather than the
staging one that stack's composefile defaults to: a staging certificate is signed
by an untrusted root, and a test whose subject is that HTTPS works cannot then
turn verification off. A hostname per run is what keeps that off the
duplicate-certificate rate limit.

Run them from the repo root. By default each one tests the most recently built
shiv package in `./package` (`./scripts/build_shiv_package.sh`); pass `from-path`
to test the `stack` on your PATH instead, or set `TEST_TARGET_STACK` (e.g. to
`"uv run stack"`).

Set `STACK_SCRIPT_DEBUG` to turn on xtrace and an environment dump. In CI it is
wired to `runner.debug`, so ticking "Enable debug logging" when re-running a
failed job turns it on for that run.

Shared helpers live in `tests/lib/common.sh`, which every test script sources as
its first line: the debug preamble, target selection, test-directory setup, and
the `wait_for_*` / teardown helpers. Put anything used by more than one test
there — these scripts were written by copying each other, and each copied helper
eventually drifted from its siblings.

## Source Layout

```
src/stack/
├── main.py                  # CLI entry point (Click commands)
├── util.py                  # Shared utilities
├── log.py                   # Logging (colored, timestamped)
├── constants.py             # Configuration constants
├── deploy/
│   ├── stack.py             # Stack model (parsed from stack.yml)
│   ├── spec.py              # Deployment specification (Spec, MergedSpec)
│   ├── deployer.py          # Abstract Deployer base class
│   ├── deployer_factory.py  # Factory: returns Docker or K8s deployer
│   ├── deployment.py        # Deployment orchestration
│   ├── deployment_context.py # Tracks deployment directory/files
│   ├── compose/             # Docker Compose deployer implementation
│   │   └── deploy_docker.py
│   └── k8s/                 # Kubernetes deployer implementation
│       ├── deploy_k8s.py
│       ├── helpers.py
│       └── cluster_info.py
├── build/                   # Container building and publishing
├── repos/                   # Git repository management
├── config/                  # Profile-based configuration
├── init/                    # Stack specification generation
├── chart/                   # Mermaid diagram generation
├── webapp/                  # Web application framework
└── data/                    # Embedded templates, K8s components
```

## Key Abstractions

- **Stack** (`deploy/stack.py`): Parsed from `stack.yml` files. Defines containers, pods, and their relationships. Supports "super stacks" (composition of stacks).
- **Spec** (`deploy/spec.py`): Deployment specification — references a stack plus deployment config (target, volumes, resources, HTTP proxy). `MergedSpec` combines multiple specs.
- **Deployer** (`deploy/deployer.py`): Abstract base with `up()`, `down()`, `ps()`, `logs()`, `execute()`, etc. Two implementations:
  - `DockerDeployer` — generates Docker Compose YAML, uses `python-on-whales`
  - `K8sDeployer` — uses the `kubernetes` Python client, supports Kind for local clusters
- **DeployerFactory** (`deploy/deployer_factory.py`): Returns the correct deployer based on `deploy-to` field in the spec (`compose`, `k8s`, `k8s-kind`).

## CLI Commands

Core commands defined in `main.py`:
- `deploy` — create a deployment from a spec file
- `manage` — manage a running deployment (start, stop, logs, exec, status)
- `build containers` — build container images
- `fetch` — clone/fetch git repositories
- `init` — generate a spec file
- `prepare` — build/download containers
- `list` — list available stacks
- `validate` — check a stack's files for referential integrity (see `docs/stack-integrity.md`)
- `config` — manage configuration profiles
- `version` / `update` / `webapp` / `chart`

Stacks can also provide custom subcommands loaded dynamically.

## Key Dependencies

- `click` — CLI framework
- `python-on-whales` (pinned 0.63.0) — Docker client
- `kubernetes` — K8s API client
- `GitPython` — git operations
- `PyYAML` / `ruamel.yaml.string` — YAML parsing
- `humanfriendly` — human-readable resource sizes

## Build & CI

- Build backend: `uv_build`
- CI runs on GitHub Actions (see `.github/workflows/`)
- Workflows: `lint.yml`, `test-unit.yml`, `test.yml`, `test-deploy.yml`, `test-deploy-k8s.yml`, `test-database.yml`, `test-deployment-control.yml`, `test-webapp.yml`, `publish.yml`
- Weekly, not per-PR, because each provisions a cloud VM: `test-deploy-k3s.yml`, `test-deploy-remote-docker.yml`
