# Ingress

Automatic configuration of HTTP routes for an ingress controller / reverse-proxy can be performed using comment-based
annotations in your `composefile.yml`.

## Example

```
services:
  backend:
    image: bozemanpass/todo-backend:stack
    ports:
      - "5000" # @stack http-proxy /api/todos

  frontend:
    image: bozemanpass/todo-frontend:stack
    ports:
      - "3000" # @stack http-proxy /
```

These annotations will instruct the `stack init` command that `frontend:3000` should be published at the root path `/`
and that `backend:5000` should be published at `/api/todos`.

The hostname to be used is set by the `--http-proxy-fqdn` (the default is the result of `socket.getfqdn()`).

The result will be `http-proxy` settings in the `init` output similar to:

```
network:
  http-proxy:
   - host-name: example.hostname.com
     routes:
      - path: /api/todos
        proxy-to: backend:5000
      - path: /
        proxy-to: frontend:3000
```

## Kubernetes

When using Kubernetes, support for [kubernetes/ingress-nginx](https://github.com/kubernetes/ingress-nginx) is built in.
SSL support is also handled automatically by [cert-manager](https://github.com/cert-manager/cert-manager) if installed.
The `cluster-issuer` to use for requesting a certificate can be specified using the `--http-proxy-clusterissuer` flag.
No additional configuration is required.

## Docker

By using [bozemanpass/docker-ingress-stack](https://github.com/bozemanpass/docker-ingress-stack), similar functionality
can be achieved with Docker.  This stack uses [nginxproxy/nginx-proxy](https://github.com/nginx-proxy/nginx-proxy) to
provide reverse proxy servies with automatically configured routes, similar to [kubernetes/ingress-nginx](https://github.com/kubernetes/ingress-nginx).

> NOTE: If you do not need SSL, you can use the `docker-ingress-no-ssl` stack instead, which does not require any `--config` options.

The `docker-ingress` stack can simply be "mixed-in" to your existing stack at deployment time like this example below:

```
# Fetch and init the docker-ingress stack
$ stack fetch repo bozemanpass/docker-ingress-stack

$ FQDN=todo.mydomain.com

# '--map-ports-to-host any-same' uses ports 80 and 443 on the host
# NOTE: The default ACME CA is https://acme-v02.api.letsencrypt.org/directory, but we override that for this example to use the staging CA.

$ stack init --stack docker-ingress \
  --output ~/specs/docker-ingress.yml \
  --map-ports-to-host any-same \
  --config ACME_CA_URI=https://acme-staging-v02.api.letsencrypt.org/directory \
  --config LETSENCRYPT_EMAIL=example@mydomain.com \
  --config LETSENCRYPT_HOST=$FQDN

# Fetch and prepare your stack (here, 'todo').
$ stack fetch repo bozemanpass/example-todo-list
$ stack prepare --stack todo

# We are using config to tell the app what the final URL will be.
$ stack init --stack todo \
  --output ~/specs/todo.yml \
  --http-proxy-fqdn $FQDN \
  --config REACT_APP_API_URL=https://${FQDN}/api/todos

# "Mix-in" the docker-ingress stack at deployment time.
$ stack deploy \
  --spec-file ~/specs/docker-ingress.yml \
  --spec-file ~/specs/todo.yml \
  --deployment-dir ~/deployments/todo
  
$ stack manage --dir ~/deployments/todo start
$ stack manage --dir ~/deployments/todo ps
id: 882964b2300de, name: stack-3285f74574bd152c-backend-1, ports: 0.0.0.0:56462->5000/tcp
id: f8f39dc35c9e4, name: stack-3285f74574bd152c-db-1, ports: 0.0.0.0:56455->5432/tcp
id: 6c4d42c1c0f03, name: stack-3285f74574bd152c-nginx-proxy-1, ports: 0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
id: 700202db6e6ab, name: stack-3285f74574bd152c-frontend-1, ports: 0.0.0.0:56454->3000/tcp
```

## Combining Stacks

It is often useful to create "super stacks" by combining and deploying multiple stacks together as a single unit.
In that case, conflicts can arise among the HTTP paths which are published by the individual stacks.  A configuration
option, `http-proxy-prefix`, is available to "shift" all the published paths of a given stack to avoid conflicts.

Example:
```
name: siwe-on-fixturenet
requires:
  stacks:
    - ref: bozemanpass/fixturenet-eth-stack
      path: stacks/fixturenet-eth
      http-proxy-prefix: /eth
    - ref: bozemanpass/siwe-express-example
      path: stacks/siwe-express-example
      http-proxy-prefix: /
```

In this case, the `fixturenet-eth` stack is shifted, so that all its published routes are prefixed with `/eth`.  This
prefix will be stripped automatically by the proxy, so that the individual services will not see a different path than
if they had been deployed directly.  The other stack in this example, `siwe-express-example`, is not shifted, and it
will be published at the root path (`/`).
