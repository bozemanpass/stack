# HTTPS with the Gateway API

On Kubernetes, stack publishes the `http-proxy` section of a deployment spec (see [ingress.md](ingress.md))
through one of two mechanisms, chosen automatically per target cluster:

- **Gateway API** — used when the cluster serves the contract described below. This is the current arrangement.
- **Ingress API** — the legacy arrangement, using the (now retired upstream) nginx ingress controller. Used
  whenever the Gateway API contract is not present, including `k8s-kind` deployments.

Nothing in the stack or spec files changes between the two: the same `http-proxy` settings are rendered as either
an `Ingress` or as Gateway API resources at deploy time. `stack manage --dir <dir> explain` shows both renderings.

## The cluster contract

A Gateway API cluster is detected by the presence of a `GatewayClass` named `traefik`. Beyond that, stack expects
(and the [machine-provisioning](https://github.com/stirlingbridge/machine-provisioning) `k3s-node.sh` script
provides by default):

- A `Gateway` named `stack-gateway` in the `kube-system` namespace, with an HTTP listener on port 8000 (traefik's
  `web` entrypoint, exposed by its service as port 80), accepting routes from all namespaces, and annotated with
  `cert-manager.io/cluster-issuer`. If the Gateway does not exist, stack creates it on first deploy.
- cert-manager with Gateway API support enabled (`--enable-gateway-api`).
- `ClusterIssuer`s (`letsencrypt-prod` by default; override with `--http-proxy-clusterissuer`) whose ACME HTTP-01
  solver is `gatewayHTTPRoute` with a `parentRef` naming the same `stack-gateway`.

stack treats `stack-gateway` as its own: it adds and removes listeners on it at deploy time. For that reason the
Gateway must not be owned by another manager (such as the traefik helm chart, whose re-syncs would drop
stack-added listeners).

## What a deployment creates

For a spec with an `http-proxy` section, `stack manage start` creates:

1. **An HTTPS listener on `stack-gateway`** for the deployment's `host-name`, named `<deployment-id>-https`,
   referencing a certificate secret named `<deployment-id>-tls`. cert-manager notices the new listener on the
   annotated Gateway and obtains a Let's Encrypt certificate for the hostname over ACME HTTP-01 (solving the
   challenge with a temporary HTTPRoute on the Gateway's HTTP listener). If an existing HTTPS listener already
   covers the hostname — in particular a machine-provisioned wildcard listener (`*.example.com`, certificate
   issued over DNS-01) — no listener is added and the existing certificate serves the deployment.
2. **An HTTPRoute** in the deployment's namespace, attached to `stack-gateway`, with one rule per `http-proxy`
   route. Non-root paths are matched by prefix and rewritten (`ReplacePrefixMatch: /`) so the backend sees
   requests at its own root, matching the behavior of the legacy Ingress arrangement. Regex paths, which the
   Ingress arrangement passed to nginx, are not supported by the Gateway API and degrade to their literal prefix
   with a warning.

`stack manage stop` deletes the HTTPRoute and removes the deployment's listener. The certificate secret is left
behind deliberately: redeploying the same hostname reuses the still-valid certificate instead of asking
Let's Encrypt for a new one.

Because the certificate belongs to the Gateway's listener rather than to the workload, everything here is plain
Kubernetes API objects — provisioning an HTTPS endpoint needs no access to the host beyond the Kubernetes API
itself, and no DNS API access (only an A/AAAA record pointing the hostname at the machine, created by whatever
means, before certificates can be issued).

## Limitations

- One `http-proxy` entry (one hostname) per deployment, as with the legacy arrangement.
- The Gateway API caps a Gateway at 64 listeners, bounding the number of individually-certified hostnames per
  machine; wildcard-listener machines are not affected.
- `k8s-kind` clusters currently use the legacy nginx ingress arrangement (without TLS, as before).
