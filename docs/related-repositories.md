# Related Repositories

`stack` is one piece of a larger set of repositories. Some are consumed directly by the tool
(wrapper schemes it fetches, companion stacks it deploys), some exist only to be fetched and
deployed by the test suite, and some are separate tools that solve the parts of the problem
`stack` deliberately does not — creating the machine, provisioning the cluster.

This page lists them and says what each one's connection to `stack` actually is. Repositories
live in the [bozemanpass](https://github.com/bozemanpass) GitHub organization unless noted;
the deployment-host tools live in [stirlingbridge](https://github.com/stirlingbridge).

## Container wrappers

Wrapper repositories provide the recipes that build an application repository with no container
build of its own into a runnable image. `stack` fetches these two automatically when a wrapper
is needed and none has been fetched yet — the list is hard-coded in
`src/stack/build/wrappers.py`. See [wrappers.md](wrappers.md).

| Repository | Relationship |
| --- | --- |
| [stack-wrapper-webapp](https://github.com/bozemanpass/stack-wrapper-webapp) | Default wrapper repo. Provides the `webapp`, `nextjs`, and `node-service` schemes and their base images for node.js applications. |
| [stack-wrapper-static-content](https://github.com/bozemanpass/stack-wrapper-static-content) | Default wrapper repo. Provides the `static-content` scheme: a repository of static HTML served by nginx. |

## Companion stacks

Stacks that implement a `stack` feature but ship as their own repository, fetched and deployed
alongside the application stack rather than built into the tool.

| Repository | Relationship |
| --- | --- |
| [docker-ingress-stack](https://github.com/bozemanpass/docker-ingress-stack) | Implements the Docker-mode HTTPS ingress described in [ingress.md](ingress.md) — the reverse proxy that `stack`'s ingress annotations configure. |
| [backup-stack](https://github.com/bozemanpass/backup-stack) | The container and stack components for the backup/restore design in [backup.md](backup.md). Initial scaffold; exercised by `tests/backup/run-test.sh`. |

## Examples and demos

Real applications that are packaged as stacks. These double as the worked examples in the
README and as fixtures for the deployment tests.

| Repository | Relationship |
| --- | --- |
| [example-todo-list](https://github.com/bozemanpass/example-todo-list) | The canonical example: React frontend, Node backend, PostgreSQL. Used in the README quickstart and by the Docker and Kubernetes deploy tests. |
| [siwe-express-example](https://github.com/bozemanpass/siwe-express-example) | Sign-in-with-Ethereum Express app with a fixturenet blockchain — a stack with substantial pre-start setup. |
| [example-stateful-container](https://github.com/bozemanpass/example-stateful-container) | Shows a container using a bind mount that retains host `uid:gid` ownership. |

## Test fixtures

Repositories that exist so the test suite has something real to fetch, build, and deploy. They
are not intended for use outside testing.

| Repository | Relationship |
| --- | --- |
| [stack-test-stacks](https://github.com/bozemanpass/stack-test-stacks) | The stack definitions used by the smoke, database, backup, and static-content tests, plus the container definitions they build (`stack-files/containers/`). The main external-stack fixture. |
| [stack-test-static-content](https://github.com/bozemanpass/stack-test-static-content) | A repository of nothing but static HTML — the input to the `static-content` wrapper in `tests/static-content-test`. |
| [test-progressive-web-app](https://github.com/bozemanpass/test-progressive-web-app) | A Next.js PWA, built by `tests/webapp-test` to exercise the webapp build path. Mirror of the upstream cerc-io repo. |
| [stack-test-project](https://github.com/bozemanpass/stack-test-project) | A minimal project repository for testing project-related tooling. |

## Deployment host tooling

`stack` deploys *to* a Docker host or a Kubernetes cluster; it does not create one. These tools
do that, and are what the docs and the k3s test reach for when a real host is needed. They are
independent projects — `stack` does not depend on them at runtime.

| Repository | Relationship |
| --- | --- |
| [stirlingbridge/machine](https://github.com/stirlingbridge/machine) | Creates and manages cloud VMs (DigitalOcean, Vultr, GCP). Used by `demo/k8s-host.sh` and `tests/k3s-deploy` to stand up a deployment host; recommended in [from-laptop-to-production.md](from-laptop-to-production.md). |
| [stirlingbridge/machine-provisioning](https://github.com/stirlingbridge/machine-provisioning) | `cloud-init` scripts that turn a fresh VM into a Docker host or single-node k3s cluster. Its `k3s-node.sh` establishes the cluster contract that [gateway-api.md](gateway-api.md) and `deploy/k8s/gateway.py` assume. |

## Agent skills

| Repository | Relationship |
| --- | --- |
| [no-paas](https://github.com/bozemanpass/no-paas) | A Claude Code plugin marketplace cataloguing the agent skills for deploying without a PaaS. `stack`'s own skill is mastered in this repo under `skills/`; `no-paas` points at it, at the `machine` and `machine-provisioning` skills, and adds the cross-tool toolchain journeys. |

## Referenced in the docs

Not part of the toolchain, but named in the documentation as concrete examples, so worth
knowing about when a doc example does not seem to come from anywhere.

| Repository | Relationship |
| --- | --- |
| [gitea-containers](https://github.com/bozemanpass/gitea-containers) | The multi-container repository whose `act-runner` container is used throughout [stack-files.md](stack-files.md) to explain `ref`, `path`, and `content-root`. |

## Dormant

Older stacks kept for reference; not exercised by any current test or doc.

[gitea-stack](https://github.com/bozemanpass/gitea-stack),
[fixturenet-eth-stack](https://github.com/bozemanpass/fixturenet-eth-stack),
[blockscout-stack](https://github.com/bozemanpass/blockscout-stack),
[din-caddy-stack](https://github.com/bozemanpass/din-caddy-stack),
[go-nitro-stack](https://github.com/bozemanpass/go-nitro-stack),
[tensor-demo-stack](https://github.com/bozemanpass/tensor-demo-stack),
[stack-test-laconicd](https://github.com/bozemanpass/stack-test-laconicd).
