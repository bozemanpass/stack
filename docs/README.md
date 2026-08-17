# BPI Stack Documentation

`stack` is a CLI tool for building, deploying, and managing groups of containerized services
("stacks") defined in a simple component model, with transparent deployment to either Docker
Compose or Kubernetes. This directory contains the documentation: how to install and use the
tool, how to author your own stacks, and how the more advanced features work.

New users should start with [install.md](install.md) and the [command reference](commands.md);
stack authors should read [stack-files.md](stack-files.md) first.

## Getting Started

| Document | Description |
| --- | --- |
| [install.md](install.md) | Installing `stack`: user install, developer mode, and scripted install for CI/test VMs. |
| [commands.md](commands.md) | Overview of the command/subcommand structure, with links to a reference page for each command in [commands/](commands/). |

## Authoring Stacks

| Document | Description |
| --- | --- |
| [stack-files.md](stack-files.md) | The `stack.yml` file format: containers, pods, pre/post-start commands, and stack composition. The core reference for stack authors. |
| [hooks.md](hooks.md) | Extending the `init` and `deploy` commands from a stack, with Python hook functions. |
| [subcommands.md](subcommands.md) | Adding stack-specific subcommands to the `stack` command line from a `subcommands` directory. |
| [wrappers.md](wrappers.md) | Container wrappers: packaging application source that has no container build of its own (static HTML, Next.js apps without a Dockerfile) into runnable images. |
| [webapp.md](webapp.md) | Building and running static, React, and Next.js webapps with `webapp build` / `webapp run`, separating compilation from environment-specific configuration. |

## Container Images

| Document | Description |
| --- | --- |
| [fetching-containers.md](fetching-containers.md) | How pre-built container images are fetched from a registry instead of built from source, and the build policies that control this. |
| [image-names.md](image-names.md) | Every scheme used for image names and tags, and the lifecycle of an image name from stack definition through build, publish, and deployment. |

## Deployment

| Document | Description |
| --- | --- |
| [developing-applications.md](developing-applications.md) | The edit-build-deploy loop for an application you are actively changing: building images from your own working tree and getting each edit into a running compose, kind, or Kubernetes deployment. |
| [from-laptop-to-production.md](from-laptop-to-production.md) | Choosing a deployment target by situation: local development, a single always-on VM for real users, or Kubernetes — and why a PaaS is not required. Start here if you know your goal but not the options. |
| [ingress.md](ingress.md) | Automatic HTTP route configuration for an ingress controller / reverse proxy via annotations in `composefile.yml`. |
| [gateway-api.md](gateway-api.md) | HTTPS on Kubernetes via the Gateway API (with the legacy Ingress API as fallback), and the cluster contract required to use it. |
| [k8s-deployment-enhancements.md](k8s-deployment-enhancements.md) | Controlling Kubernetes pod placement with node affinity rules in the deployment spec. |
| [kube-config.md](kube-config.md) | Naming the cluster credential by reference — an environment variable, a file, or a secret store command — so that a deployment directory committed to git contains no kubeconfig. |
| [secrets.md](secrets.md) | Secret environment variables for the deployed containers, declared in the stack and injected at deploy time — generated or pulled by reference — so that no value sits in the stack files, the spec, or the deployment artifacts. |

## Design Proposals

| Document | Description |
| --- | --- |
| [backup.md](backup.md) | Backing up and restoring the persistent data a running stack accumulates: how to configure it, and how to restore into a new deployment after losing a cluster or to seed copies of a dataset. |
| [backup-implementation.md](backup-implementation.md) | How the Docker target's deploy-time pass was designed. Historical; [backup.md](backup.md) is the current description. |

## Project

| Document | Description |
| --- | --- |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute: developer-mode install, coding standards, and submitting changes. |
| [recent-features.md](recent-features.md) | Changelog of recently added features, with links to the pull requests that introduced them. |
| [related-repositories.md](related-repositories.md) | The other repositories in the `stack` orbit — wrapper schemes, companion stacks, examples, test fixtures, and the host-provisioning tools — and each one's relationship to this project. |
