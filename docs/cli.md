# stack

Sub-commands and flags

## fetch stack repo
```
$ stack fetch repo bozemanpass/example-todo-list
```

## list stacks

```
$ stack list
fixturenet-eth
siwe-express-example
siwe-on-fixturenet
todo
```
Filter:
```
$ stack list fixturenet
fixturenet-eth
siwe-on-fixturenet
```

Show paths and filter:
```
$ stack list --show-path todo
todo         /home/example/.config/stack/repos/github.com/bozemanpass/example-todo-list/stacks/todo
```

## prepare the stack containers

Check if the containers are ready:

```
$ stack checklist --stack todo
bozemanpass/todo-frontend:stack         needs to be built
bozemanpass/todo-backend:stack          needs to be built

Run 'stack prepare --stack todo' to prepare missing containers.
```

Download repos and build containers:
```
$ stack prepare --stack todo
```
Build a specific container:
```
$ stack prepare --stack todo --include-containers "bozemanpass/todo-frontend"
```
Force a full rebuild of container images:
```
$ stack prepare --stack todo --build-policy build-force
```

Now check again:
```
$ stack checklist --stack todo
bozemanpass/todo-frontend:d87d76671ad7dde247a328716c15827de9c1a89a         ready
bozemanpass/todo-backend:d87d76671ad7dde247a328716c15827de9c1a89a          ready

All containers are ready to use.
```

See [fetching-containers](fetching-containers.md) for more information on fetching and building container images.

## init

Create a configuration spec file with the default values:
```
$ stack init --stack todo --output todo.yml
```

Map stack ports to localhost:
```
$ stack init --stack todo --output todo.yml --map-ports-to-host localhost-same
```

Set a configuration value:
```
$ stack init --stack todo --output todo.yml \
    --map-ports-to-host localhost-same \
    --config REACT_APP_API_URL=http://127.0.0.1:5000/api/todos
```

Full Kubernetes configuration with image registry, HTTP ingress, and environment settings:
```
$ stack init \
    --deploy-to k8s \
    --stack todo \
    --output todo.yml                         \
    --image-registry $IMAGE_REGISTRY \
    --kube-config /path/to/kubeconfig.yaml \
    --http-proxy-fqdn example-todo.bpi.servesthe.world \
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

List service names:
```
$ stack manage --dir ~/deployments/todo services
```

Execute a command in a running container:
```
$ stack manage --dir ~/deployments/todo exec frontend 'node --version'
```
