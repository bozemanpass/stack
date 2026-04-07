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

Tests are **bash shell scripts**, not pytest. They require Docker and/or Kubernetes (Kind) to be available.

```bash
# Smoke tests (basic CLI functionality)
./tests/smoke-test/run-smoke-test.sh

# Docker deployment tests
./tests/deploy/run-deploy-test.sh

# Kubernetes deployment tests
./tests/k8s-deploy/run-k8s-deploy-test.sh
```

The smoke tests require building a shiv package first (`./scripts/build_shiv_package.sh`).

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
- Workflows: `lint.yml`, `test.yml`, `test-deploy.yml`, `test-deploy-k8s.yml`, `test-database.yml`, `test-webapp.yml`, `publish.yml`
