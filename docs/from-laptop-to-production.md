# From Laptop to Production

The rest of this documentation explains *how* to use `stack`: the file formats, the
commands, the deployment targets. This page addresses an earlier question: given the
situation you are actually in, which of those options do you want, and why?

## What "deployment" means

A system under development runs where it was built — on the developer's machine, started
by hand, gone when the laptop lid closes. Deployment is the step that changes that: making
the system run on infrastructure that stays up, reachable by the people who need it, at a
stable address. Nothing about your code changes; what changes is where and how it runs.

`stack` treats the definition of your system (the stack) as separate from any decision
about where it runs (the deployment). You define the stack once; each deployment is that
definition plus a target. This page is about choosing the target.

## Three situations

### "I want to run it here on my machine"

Deploy to Docker Compose with ports mapped to localhost:

```
stack init --stack <stack> --output spec.yml --deploy-to compose --map-ports-to-host localhost-same
```

This is the development loop, covered by the [README quick start](../README.md). It is
also the right choice for trying out someone else's published stack.

### "I want colleagues and the public to reach it, running all the time"

The system works on your laptop; now it needs to survive the laptop turning off and be
reachable at a real address. **This situation does not require Kubernetes.** The simple,
robust answer is one plain virtual machine:

1. Rent a small VM from any hosting provider — the companion
   [machine](https://github.com/stirlingbridge/machine) tool can create and manage one on
   DigitalOcean or Vultr with a couple of commands, or use any provider's console.
2. Point a DNS name at it.
3. Install `stack` on the VM ([install.md](./install.md) includes a scripted install for
   fresh VMs) and deploy exactly as you did locally, still with `--deploy-to compose`,
   adding an HTTP reverse proxy for the public hostname (see [ingress.md](./ingress.md)).

A single modest VM comfortably runs a database-backed web application serving real
traffic, costs a few dollars a month, and involves no new concepts beyond the deployment
you already ran locally. When the VM needs to be bigger, resize it. This is where most
systems can happily stay.

### "I'm running many apps, or need real scale"

Kubernetes (`--deploy-to k8s`) earns its complexity when a single VM stops being the
right shape: multiple applications sharing a pool of machines, horizontal scaling,
automated HTTPS certificate issuance per app, zero-downtime restarts, or offering
hosting to others (the roll-your-own-PaaS case). The same stack deploys unchanged; what
you take on is operating (or renting) a cluster, an image registry, and DNS/TLS machinery
— see [gateway-api.md](./gateway-api.md) and
[k8s-deployment-enhancements.md](./k8s-deployment-enhancements.md).

`k8s-kind` (Kubernetes in local Docker) exists for developing and testing the k8s shape
of a deployment without a real cluster; it is not itself a production target.

## Why not just use a PaaS?

Platform-as-a-service products (Heroku, Vercel, Fly, and the like) answer the second
situation with convenience: connect a repo, get a URL. The costs arrive later: pricing
that scales faster than a VM bill, the platform deciding what shapes of system you may
run (try putting a database, a background worker, and a custom binary on one), and
configuration accreting in platform-proprietary files so that leaving means re-doing the
deployment work from scratch.

The trade has real upside — someone else carries the pager — but it is worth knowing
that the convenience is separable from the lock-in. `stack` aims to give you the same
"define once, deploy with one command" experience on commodity infrastructure you
control: an ordinary VM, or an ordinary cluster. Because the stack definition is
target-neutral, the exit door stays open in every direction — laptop to VM to cluster to
a different provider — without rewriting anything.

## Moving between targets

The stack definition never changes; only the `stack init` invocation does. Local compose
to public VM is typically just re-running the same commands on the VM. Compose to k8s
adds an image registry (`--image-registry`, plus `stack manage push-images`) and the
public hostname flags (`--http-proxy-fqdn`, `--http-proxy-target`). The [README quick
start](../README.md) shows the same stack deployed both ways.
