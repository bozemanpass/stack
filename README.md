# Stack

Stack allows building and deployment of a suite of related applications as a single "stack".

## Quick Start

### Docker

```
# clone / build
stack fetch repo bozemanpass/example-todo-list
stack prepare --stack todo

# init
stack init \
  --stack todo \
  --output todo.yml \
  --map-ports-to-host localhost-same

# create the deployment from the config
stack deploy --spec-file todo.yml --deployment-dir ~/deployments/todo

# start / status / logs / stop
stack manage --dir ~/deployments/todo start
stack manage --dir ~/deployments/todo status
stack manage --dir ~/deployments/todo logs
stack manage --dir ~/deployments/todo stop
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
stack deploy --spec-file todo.yml --deployment-dir ~/deployments/todo

# push image tags for this deployment to the image registry used by Kubernetes
stack manage --dir ~/deployments/todo push-images

# start / status / logs / stop
stack manage --dir ~/deployments/todo start
stack manage --dir ~/deployments/todo status
stack manage --dir ~/deployments/todo logs
stack manage --dir ~/deployments/todo stop
```

## Example Stacks

 - [Gitea](https://about.gitea.com/) stack: https://github.com/bozemanpass/gitea-stack
 - A [sign in with Ethereum](https://docs.login.xyz/) web app with fixturenet blockchain: https://github.com/bozemanpass/siwe-express-example

## Install

Stack runs on Linux, macos and Windows under WSL2. Both x86-64 and ARM64 are supported.

### Tire Kicking
To get started quickly on a fresh Ubuntu 24.04 instance (e.g, a Digital Ocean droplet); [try this script](./scripts/quick-install-linux.sh).

**WARNING:** Always review downloaded scripts prior to running them so that you know what going to happen to your machine.

### Lazy Mode
Stack is written in Python and so needs a recent Python 3 on the machine. It also needs either docker or podman installed, and these utilities: git, jq. The [full installation instructions](./docs/install.md) show how to get these but if you're allready set up, proceed:

Stack is distributed as a single-file self-extracting script. The latest release can be downloaded like this:
```bash
curl -L -o ~/bin/stack https://github.com/bozemanpass/stack/releases/latest/download/stack
chmod +x ~/bin/stack
```
### Hard Mode
Detailed documentation on the installation of stack and its prerequisites as well as how to update stack can be found [here](./docs/install.md).
## Learn More
 - [Stack commands](./docs/cli.md)
 - [Recent New Features](./docs/recent-features.md)
## Contributing

See the [CONTRIBUTING.md](/docs/CONTRIBUTING.md) for developer mode install.

## Origin

This is a fork of https://git.vdb.to/cerc-io/stack-orchestrator intended for more general use.
