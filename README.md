# Stack

Stack allows building and deployment of a suite of related applications as a single "stack".

## Quick Start

### Docker

```
# clone / build
stack fetch stack bozemanpass/example-todo-list
stack build containers --stack ~/bpi/example-todo-list/stacks/todo

# init
stack init \
  --stack ~/bpi/example-todo-list/stacks/todo \
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
# clone / build
stack fetch stack bozemanpass/example-todo-list
stack build containers \
    --stack ~/bpi/example-todo-list/stacks/todo \
    --image-registry $IMAGE_REGISTRY \
    --publish-images

# set some defaults
stack config set image-registry $IMAGE_REGISTRY
stack config set kube-config /path/to/.kube/config

# init
stack init \
    --stack ~/bpi/example-todo-list/stacks/todo \
    --output todo.yml \
    --deploy-to k8s \
    --http-proxy-fqdn example-todo.bpi.servesthe.world \
    --config REACT_APP_API_URL=https://example-todo.bpi.servesthe.world/api/todos

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

## Install

**To get started quickly** on a fresh Ubuntu instance (e.g, Digital Ocean); [try this script](./scripts/quick-install-linux.sh). **WARNING:** always review scripts prior to running them so that you know what is happening on your machine.

For any other installation, follow along below and **adapt these instructions based on the specifics of your system.**


Ensure that the following are already installed:

- [Python3](https://wiki.python.org/moin/BeginnersGuide/Download): `python3 --version` >= `3.8.10` (the Python3 shipped in Ubuntu 20+ is good to go)
- [Docker](https://docs.docker.com/get-docker/): `docker --version` >= `20.10.21` or [podman](https://podman.io/) `podman --version` >= `3.4.4`
- [jq](https://stedolan.github.io/jq/download/): `jq --version` >= `1.5`
- [git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git): `git --version` >= `2.10.3`

Note: if installing docker-compose via package manager on Linux (as opposed to Docker Desktop), you must [install the plugin](https://docs.docker.com/compose/install/linux/#install-the-plugin-manually), e.g. :

```bash
mkdir -p ~/.docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/download/v2.11.2/docker-compose-linux-x86_64 -o ~/.docker/cli-plugins/docker-compose
chmod +x ~/.docker/cli-plugins/docker-compose
```

Next decide on a directory where you would like to put the stack program. Typically, this would be 
a "user" binary directory such as `~/bin` or perhaps `/usr/local/bin/stack` or possibly just the current working directory.

Now, having selected that directory, download the latest release from [this page](https://github.com/bozemanpass/stack/tags) into it (we're using `~/bin` below for concreteness but edit to suit if you selected a different directory). Also be sure that the destination directory exists and is writable:

```bash
curl -L -o ~/bin/stack https://github.com/bozemanpass/stack/releases/latest/download/stack
```

Give it execute permissions:

```bash
chmod +x ~/bin/stack
```

Ensure `stack` is on the [`PATH`](https://unix.stackexchange.com/a/26059)

Verify operation (your version will probably be different, just check here that you see some version output and not an error):

```
stack version
Version: 2.0.0-fb86d3c-202503251632
```

### Update
If `stack` was installed using the process above, it is able to self-update to the current latest version by running:

```bash
stack update
```

#### Alternate Update Locations (e.g., a fork)

If you want to update from a different location (e.g., a fork), you can do so setting the distribution URL to use:

Save the alternate distribution URL in `~/.stack/config.yml`:

```bash
stack config set distribution-url https://github.com/example-org/my-stack-fork/releases/latest/download/stack
```

## Contributing

See the [CONTRIBUTING.md](/docs/CONTRIBUTING.md) for developer mode install.

## Origin

This is a fork of https://git.vdb.to/cerc-io/stack-orchestrator intended for more general use.
