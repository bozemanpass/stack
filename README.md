# Stack

Stack allows building and deployment of a system of related containerized applications as a single "stack". Transparently deploy to local Docker, Podman or to remote Kubernetes.

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
stack deploy --spec-file todo.yml --deployment-dir ~/deployments/todo-docker

# start / status / logs / stop
stack manage --dir ~/deployments/todo-docker start
stack manage --dir ~/deployments/todo-docker status
stack manage --dir ~/deployments/todo-docker logs
stack manage --dir ~/deployments/todo-docker stop
```

### Kubernetes

```
# set some defaults for the k8s instance
stack config set image-registry registry.myexample.com/myimages
stack config set kube-config /path/to/.kube/config

# clone / build
stack fetch repo bozemanpass/example-todo-list
stack prepare --stack todo --publish-images

# init
stack init \
    --stack todo \
    --output todo.yml \
    --deploy-to k8s \
    --http-proxy-fqdn example-todo.myexample.com \
    --config REACT_APP_API_URL=https://example-todo.myexample.com/api/todos

# create the deployment from the config
stack deploy --spec-file todo.yml --deployment-dir ~/deployments/todo-k8s

# push image tags for this deployment to the image registry used by Kubernetes
stack manage --dir ~/deployments/todo push-images

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
 - [Recent New Features](./docs/recent-features.md)
## Contributing

See the [CONTRIBUTING.md](/docs/CONTRIBUTING.md) for developer mode install.

## Origin

This is a fork of https://git.vdb.to/cerc-io/stack-orchestrator intended for more general use.
