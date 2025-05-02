# stack

Sub-commands and flags

## fetch stack
```
$ stack fetch stack bozemanpass/example-todo-list
```

## fetch repositories

Clone the repositories for a stack:
```
$ stack fetch repositories --stack ~/bpi/example-todo-list/stacks/todo
```
Pull latest commits from origin:
```
$ stack fetch repositories --stack ~/bpi/example-todo-list/stacks/todo --pull
```
Use SSH rather than https:
```
$ stack fetch repositories --stack ~/bpi/example-todo-list/stacks/todo --git-ssh
```

## build containers

Build all containers:
```
$ stack build containers --stack ~/bpi/example-todo-list/stacks/todo
```
Build a specific container:
```
$ stack build containers --stack ~/bpi/example-todo-list/stacks/todo --include "bpi/todo-frontend"
```
Force full rebuild of container images:
```
$ stack build containers --stack ~/bpi/example-todo-list/stacks/todo --build-policy build-force
```

See [fetching-containers](fetching-containers.md) for more information on fetching, building,
and checking for container images.

## config

Create a configuration spec file with the default values:
```
$ stack config init --stack ~/bpi/example-todo-list/stacks/todo --output todo.yml
```

Map stack ports to localhost:
```
$ stack config init --stack ~/bpi/example-todo-list/stacks/todo --output todo.yml --map-ports-to-host localhost-same
```

Set a configuration value:
```
$ stack config init --stack ~/bpi/example-todo-list/stacks/todo --output todo.yml \
    --map-ports-to-host localhost-same \
    --config REACT_APP_API_URL=http://127.0.0.1:5000/api/todos
```

Full Kubernetes configuration with image registry, HTTP ingress, and environment settings:
```
$ stack config --deploy-to k8s init \
    --stack ~/bpi/example-todo-list/stacks/todo \
    --output todo.yml                         \
    --image-registry $IMAGE_REGISTRY \
    --kube-config /path/to/kubeconfig.yaml \
    --http-proxy example-todo.bpi.servesthe.world:frontend:3000 \
    --http-proxy example-todo.bpi.servesthe.world/api/todos:backend:5000 \
    --config REACT_APP_API_URL=https://example-todo.bpi.servesthe.world/api/todos
```

## deploy

Deploy the stack according to the configuration spec:

```
$ stack deploy --spec-file todo.yml --deployment-dir ~/deployments/todo
```

## manage

Push image tags for stack containers (needed with Kubernetes and external image registries):
```
$ stack manage --deployment-dir ~/deployments/todo push-images
```

Start the stack:
```
$ stack manage --deployment-dir ~/deployments/todo start
```

Stop the stack:
```
$ stack manage --deployment-dir ~/deployments/todo stop
```

Stop the stack and delete volumes:
```
$ stack manage --deployment-dir ~/deployments/todo stop --delete-volumes
```

Reload to pick up config changes:
```
$ stack manage --deployment-dir ~/deployments/todo reload
```

Show basic stack and container status:
```
$ stack manage --deployment-dir ~/deployments/todo status
```

List running container ids, names, and ports:
```
$ stack manage --deployment-dir ~/deployments/todo ps
```

Show port mapping details for a specific service and port:
```
$ stack manage --deployment-dir ~/deployments/todo port frontend 3000
```

Print service logs:
```
$ stack manage --deployment-dir ~/deployments/todo logs
```

Follow logs (limited to _n_ lines):
```
$ stack manage --deployment-dir ~/deployments/todo logs -f -n 10
```

Execute a command in a running container:
```
$ stack manage --dir ~/deployments/todo exec frontend 'node --version'
```