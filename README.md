# Stack

Stack allows building and deployment of a system of related containerized applications as a single "stack". Transparently deploy to local Docker, Podman or to remote Kubernetes.

![Building a three-container todo app — front end, API and PostgreSQL — and deploying it with stack, first to local Docker and then, unchanged, to a Kubernetes cluster over HTTPS](./docs/images/quickstart.gif)

_An unedited recording of the [Docker quick start](#docker) below, followed by the same stack deployed to a real Kubernetes cluster. Regenerate it with `./demo/k8s-host.sh create && ./demo/record-quickstart.sh` (see [demo/README.md](./demo/README.md))._

## What is Stack good for?
Stack is useful for a wide category of software applications including those that have a web app component, back-end services and optionally a database: web systems.
Development of such a system ususally begins on a laptop where it's quick and easy to prototype concepts, try things out and iterate.
Once the system is ready for users it needs somewhere to run that stays up — reachable by colleagues, customers, 
or the public at a real URL, whether or not the laptop lid is open. That step is called _deployment_, and the common option today is to hand it to 
one of the "Platforms". The PaaS can provide hosting but also brings a growing bill, limits on what you can run, and configuration you can't take with you. 
Stack is the PaaS-free alternative: define your system once, then deploy that same definition with one command to 
local Docker while you develop, to an ordinary rented VM to serve real users, or to a Kubernetes cluster when you genuinely need scale, with no vendor lock-in 
at any step. If you're wondering which of those you need, start with [From Laptop to Production](./docs/from-laptop-to-production.md).

## Quick Start

Let's build and deploy an [example stack](https://github.com/bozemanpass/example-todo-list) for the canonical "Todo" web app (LLM-generated of course).
This stack comprises the web app front-end, an api back-end and its PostgreSQL database.

First we'll deploy to local Docker. Then deploy the same stack to Kubernetes.

### Docker

```
# clone / build
stack fetch repo bozemanpass/example-todo-list
stack prepare --stack todo

# init
stack init \
  --stack todo \
  --output todo.yml \
  --deploy-to compose \
  --map-ports-to-host localhost-same

# create the deployment from the config
# (the parent directory must already exist)
mkdir -p ~/deployments
stack deploy --spec-file todo.yml --deployment-dir ~/deployments/todo-docker

# start / status / logs / stop
stack manage --dir ~/deployments/todo-docker start
stack manage --dir ~/deployments/todo-docker status
stack manage --dir ~/deployments/todo-docker logs
stack manage --dir ~/deployments/todo-docker stop
```

### Kubernetes

```
# clone / build
stack fetch repo bozemanpass/example-todo-list
stack prepare --stack todo --publish-images --image-registry registry.myexample.com/myimages

# init
stack init \
    --stack todo \
    --output todo.yml \
    --deploy-to k8s \
    --kube-config /path/to/.kube/config \
    --image-registry registry.myexample.com/myimages \
    --http-proxy-fqdn example-todo.myexample.com \
    --config REACT_APP_API_URL=https://example-todo.myexample.com/api/todos

# create the deployment from the config
# (the parent directory must already exist)
mkdir -p ~/deployments
stack deploy --spec-file todo.yml --deployment-dir ~/deployments/todo-k8s

# push image tags for this deployment to the image registry used by Kubernetes
stack manage --dir ~/deployments/todo-k8s push-images

# start / status / logs / stop
stack manage --dir ~/deployments/todo-k8s start
stack manage --dir ~/deployments/todo-k8s status
stack manage --dir ~/deployments/todo-k8s logs
stack manage --dir ~/deployments/todo-k8s stop
```

## Example Stacks

 - [Gitea](https://about.gitea.com/) stack: https://github.com/bozemanpass/gitea-stack
 - A [sign in with Ethereum](https://docs.login.xyz/) web app with fixturenet blockchain: https://github.com/bozemanpass/siwe-express-example
 - Todo List Web App with back-end: https://github.com/bozemanpass/example-todo-list

For the wider set of related projects — wrapper schemes, companion stacks, test fixtures and the
host-provisioning tools — see [docs/related-repositories.md](./docs/related-repositories.md).

## Install

Stack runs on Linux, macos and Windows under WSL2. Both x86-64 and ARM64 are supported.

### Tire Kicking
To get started quickly on a fresh Ubuntu 24.04 instance (e.g, a Digital Ocean droplet); [try this script](./scripts/quick-install-linux.sh).

**WARNING:** Always review downloaded scripts prior to running them so that you know what going to happen to your machine.

### Install with uv
If you have [uv](https://docs.astral.sh/uv/getting-started/installation/) installed:
```bash
uv tool install --from git+https://github.com/bozemanpass/stack stack
```

### Download a release
Stack is written in Python and so needs a recent Python 3 on the machine. It also needs either docker or podman installed, and these utilities: git, jq. The [full installation instructions](./docs/install.md) show how to get these but if you're already set up, proceed:

Stack is distributed as a single-file self-extracting script. The latest release can be downloaded like this:
```bash
curl -L -o ~/bin/stack https://github.com/bozemanpass/stack/releases/latest/download/stack
chmod +x ~/bin/stack
```
### Hard Mode
Detailed documentation on the installation of stack and its prerequisites as well as how to update stack can be found [here](./docs/install.md).
## Learn More
 - [Stack commands](./docs/commands.md)
 - [Stack files](./docs/stack-files.md)
 - [Developing an application with stack](./docs/developing-applications.md)
 - [Container wrappers](./docs/wrappers.md)
 - [Building and running webapps](./docs/webapp.md)
 - [Recent New Features](./docs/recent-features.md)
## Contributing

See the [CONTRIBUTING.md](/docs/CONTRIBUTING.md) for developer mode install.

## Origin

This is a fork of https://git.vdb.to/cerc-io/stack-orchestrator intended for more general use.
