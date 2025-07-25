# Ingress

HTTP ingress / reverse proxy support is configured using comment-based annotations in your `composefile.yml`.

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

This will publish the `frontend` service on port `3000` at path `/` and the `backend` service on port `5000` at path `/api/todos`.
The domain name to be used is set by the `--htpp-`

When using Kubernetes, support for an NGINX ingress controller is built in.



It is possible to provide a similar
experience with Docker by mixing-in a stack which provides an NGINX reverse proxy.

Out of the box, [bozemanpass/docker-ingress-stack](https://github.com/bozemanpass/docker-ingress-stack) 
