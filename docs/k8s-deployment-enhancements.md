# K8S Deployment Enhancements
## Controlling pod placement
The placement of pods created as part of a stack deployment can be controlled to either avoid certain nodes, or require certain nodes.
### Pod/Node Affinity
Node affinity rules applied to pods target node labels. The effect is that a pod can only be placed on a node having the specified label value. Note that other pods that do not have any node affinity rules can also be placed on those same nodes. Thus node affinity for a pod controls where that pod can be placed, but does not control where other pods are placed.

Node affinity for stack pods is specified in the deployment's `spec.yml` file as follows:
```
node-affinities:
  - label: nodetype
    value: typeb
```
This example denotes that the stack's pods should only be placed on nodes that have the label `nodetype` with value `typeb`.

Note that these rules apply to every pod in the deployment.  For the narrower case of placing a pod on the node that
holds a volume's data, put the affinity on the volume instead — see [volumes.md](volumes.md) — which constrains only
the pods that mount it.
### Node Taint Toleration
K8s nodes can be given one or more "taints". These are special fields (distinct from labels) with a name (key) and optional value.
When placing pods, the k8s scheduler will only assign a pod to a tainted node if the pod posesses a corresponding "toleration".
This is metadata associated with the pod that specifies that the pod "tolerates" a given taint.
Therefore taint toleration provides a mechanism by which only certain pods can be placed on specific nodes, and provides a complementary mechanism to node affinity.

Taint toleration for stack pods is specified in the deployment's `spec.yml` file as follows:
```
node-tolerations:
  - key: nodetype
    value: typeb
```
This example denotes that the stack's pods will tolerate a taint: `nodetype=typeb`

## Sandboxed runtimes (RuntimeClass)
A cluster can offer more than one container runtime, exposed as `RuntimeClass` objects. The one this
support exists for is [Kata Containers](https://katacontainers.io/), which runs a pod inside a
lightweight VM with its own kernel, so that a container escape reaches the guest rather than the node.

Which runtime a stack's pods use is specified in the deployment's `spec.yml` file as follows:
```
runtime-class:
  default: kata
  services:
    user-code: kata
    postgres:
```
Both keys are optional. `default` names the class for every service in the deployment; an entry under
`services` names the class for one service and takes precedence over the default, and an entry with an
empty value opts that service back out and returns it to the cluster's default runtime.

The per-service form is the one to reach for. A guest VM costs memory and start-up time that a
container does not, and the isolation is usually wanted for the one service running untrusted code
rather than for the database next to it. `default` is there for the deployment where every pod really
does want it.

A named class must already exist on the cluster: k8s rejects a pod naming a `RuntimeClass` it does not
have, rather than falling back to the default runtime. Nothing here is specific to kata — any class the
cluster publishes (`gvisor`, and so on) can be named.

Three things behave differently under a sandboxed runtime, and are worth knowing before turning it on:

- **Privileged containers.** The host privileges `security.<service>.privileged` asks for are the
  guest's, not the host's, inside a VM. Asking for both on one service is rejected at deployment
  create time rather than left to be debugged from inside the guest.
- **Resource limits size the VM.** A container with no limits shares the node; a guest gets a fixed
  allocation. Set `resources.containers.<service>` explicitly for a sandboxed service rather than
  relying on the default.
- **Volumes cross the guest boundary.** Host paths (including a volume with a
  [node affinity](volumes.md)) reach the guest over a filesystem share rather than directly, which
  works but does not perform like a local disk.

A `runtime-class` on a `compose` deployment is an error rather than an ignored key: a spec that asked
for isolation and silently got an ordinary container looks exactly like one that worked.

## Testing
Node affinity and taint toleration are covered by `tests/k8s-deployment-control/run-test.sh`, which builds a
four node kind cluster with labelled workers, one of them tainted, and checks that the
deployment's pod lands on the single node the affinity and toleration between them permit.

`runtime-class` is covered in two places, because the two halves of it need very different things.
That the right pods and only those name the class -- and that the spec validation above rejects what
it should -- is asserted with no cluster at all, in `tests/unit/test_k8s_runtime_class.py`. That the
class then does something is `tests/kata/run-test.sh`, which runs only against a real cluster
(`tests/k3s-deploy/`, provisioned with `STACK_K3S_KATA=true`): kata needs a runtime on the nodes and a
host that allows nested virtualization, neither of which kind can offer.

That test deploys two stacks into one deployment, gives one of the two services a `runtime-class`, and
compares kernel versions. A container shares the node's kernel and cannot do otherwise, so the
sandboxed service reporting a kernel that is not the node's is the isolation itself; the other service
reporting one that *is* the node's, in the same deployment, is what says the per-service form left it
alone.

