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

Formatting uses `black` (available via `uv run black`). Linting config is in `tox.ini`.

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
```

There are three deployment targets, and a test that works against more than one
calls `select_deploy_target` (in `tests/lib/common.sh`) and is pointed at one
with `STACK_TEST_TARGET`: `compose` (the default), `kind`, or `remote`. Tests
that are only about general behaviour stay on compose; the ones likely to find
target-specific bugs — currently `app-deploy` and `database` — are written to
run on any of the three. Anything genuinely target-shaped belongs in
`select_deploy_target` rather than in an `if` inside a test.

Which combinations CI actually runs is a separate question from which ones a
test supports, and is decided by cost: `app-deploy` and `database` both run on
compose and kind per-PR, and on remote weekly.

Compose is worth keeping in that set for a reason beyond docker coverage: it is
the only target that does not restart a failed container, so a service that only
ever comes up because something restarted it fails there and passes on k8s.

The `remote` target needs a real cluster, which costs money and minutes, so it
is never triggered per-PR. `tests/k3s-deploy/with-k3s-cluster.sh` provisions one
on a cloud VM and runs the test scripts named on its command line against it,
sharing the one cluster; the "Real K8S Deploy Test" workflow runs it weekly and
on manual dispatch.

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
- Workflows: `lint.yml`, `test-unit.yml`, `test.yml`, `test-deploy.yml`, `test-deploy-k8s.yml`, `test-database.yml`, `test-webapp.yml`, `publish.yml`
