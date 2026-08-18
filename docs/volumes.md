# Volumes

A stack's composefiles declare named volumes, and the deployment spec decides where each
one's data actually lives.  The spec's `volumes:` section maps each volume name to a path
— or to nothing — and the same entry means something different on each deployment target,
because "a path" does: on `compose` it is a directory on the machine running Docker, on
`k8s-kind` a directory on this machine bind-mounted into the local cluster's node, and on
`k8s` a directory on the remote cluster's node.

`stack init` writes a sensible default for the chosen target, so none of this needs
attention until a volume's data has to live somewhere in particular — a dataset on an
external drive, a directory maintained by another application, or (on Kubernetes) a known
path on the node instead of wherever the storage provisioner puts things.

## Docker Compose

`init` maps every volume to `./data/<name>`:

```yaml
volumes:
  db-data: ./data/db-data
```

A relative path is resolved against the deployment directory, and `deploy` creates the
directory and generates a bind mount for it.  The data travels with the deployment: back
up or move the deployment directory and the data goes along.

To place a volume somewhere else, edit the spec before running `deploy` and use an
absolute path:

```yaml
volumes:
  db-data: /mnt/bigdisk/db-data
```

The directory is bind-mounted as-is, so anything already in it is visible to the
containers — this is the route for consuming a dataset that exists before the deployment
does.

## Kubernetes (remote cluster)

For a `deploy-to: k8s` spec, `init` leaves every volume unmapped:

```yaml
volumes:
  db-data:
```

An unmapped volume becomes a bare PersistentVolumeClaim, and the cluster's default
storage class decides where the bytes live.  On k3s, for example, the bundled local-path
provisioner puts them under `/var/lib/rancher/k3s/storage/pvc-<uuid>_...` on whichever
node the pod lands on.  This is the right default: it needs nothing from the cluster
beyond a working storage class, and most deployments never care where the data is.

To bind a volume to a **specific directory on the node**, map it to an absolute path:

```yaml
volumes:
  db-data: /srv/my-dataset
```

Instead of leaving the claim to the provisioner, `deploy` then creates an explicit
`hostPath` PersistentVolume at that path, with storage class `manual`, and a claim bound
to it by name.  The pod mounts the claim as usual and ends up reading and writing
`/srv/my-dataset` on its node.  As on the other targets, pre-existing contents are
visible to the containers.

Things to know before relying on this:

- **The path must be absolute.**  It names a directory on a cluster node, so there is
  nothing sensible to resolve a relative path against; `deploy` rejects one.
- **The bare form does not pin the pod to the node that has the data.**  On a multi-node
  cluster the pod can land on a node where the path is empty or absent, so a bare path is
  for the case where placement is already settled — a single-node cluster.  Where it is
  not, name the node as below.
- **The directory should already exist, with usable permissions.**  The mount is taken
  as-is: Kubernetes does not fix up ownership the way a provisioned volume gets
  `fsGroup` treatment, so the directory must be readable (and writable, if the container
  writes) by the uid the container runs as.
- **The declared size is bookkeeping.**  A node-path volume is not quota-limited; the
  capacity (from `resources`, below) only has to be large enough for the claim to bind.

### Placing the pod where the data is

On a multi-node cluster, the volume entry can also say which node(s) hold the path, in
the same label/value vocabulary as the deployment-wide
[node affinity controls](k8s-deployment-enhancements.md) — naming one node is the
`kubernetes.io/hostname` label:

```yaml
volumes:
  db-data:
    path: /srv/my-dataset
    affinity:
      label: kubernetes.io/hostname
      value: worker-2
```

The affinity rides on the PersistentVolume (which becomes a `local` volume rather than a
`hostPath` one), so the scheduler places any pod mounting the claim onto a matching node
— only the pods that use the volume are constrained, and nothing else about the
deployment has to know.  A label shared by several nodes works too, for data replicated
onto each of them.

The mapping form is only meaningful for `deploy-to: k8s` — on the other targets the
data lives on this machine and there is no placement to control — and `deploy` rejects
an `affinity` anywhere else rather than ignoring it.

## Kubernetes (kind)

For a `deploy-to: k8s-kind` spec, `init` maps volumes to `./data/<name>` just as on
compose, and the path locates the data **on this machine**, not inside the cluster: the
directory is bind-mounted into the kind node when the cluster is created, and an explicit
PersistentVolume inside the node points at the mount.  A relative path is resolved
against the deployment directory.

This matters because stopping a kind deployment deletes its cluster: the host directory
is what survives, so the data outlives the cluster, and the next start finds it again —
the same lifecycle as a compose deployment.

An absolute path works the same way it does on compose — the named local directory, with
whatever is already in it, is mounted into the node and from there into the pod.  Because
the mounts are wired into the cluster's own configuration at creation time, a change to
the spec's `volumes:` section takes effect on the next start, not on a running cluster.

## Sizing

On the Kubernetes targets a volume's requested capacity comes from the spec's
`resources` section, defaulting to 2Gi:

```yaml
resources:
  volumes:
    db-data:
      reservations:
        storage: 10Gi
```

For a provisioner-allocated claim this is a real request that the storage class must be
able to satisfy.  For a path-mapped (`hostPath`) volume it only sizes the claim/volume
pair, as noted above.

## Read-only volumes and configmaps

On the Kubernetes targets, a read-only volume whose name contains `config` is turned
into a ConfigMap by `init` (listed under `configmaps:` in the spec rather than
`volumes:`): its files are baked into the deployment as cluster objects, so there is no
host directory involved at all.  Everything else on this page concerns read-write data
volumes.

## Finding where the data ended up

`stack manage status` reports each of the deployment's volumes along with the location of
its data, which is worth having on any target and is close to essential where the spec
does not say: a provisioner-allocated claim only learns its node and path when it binds.

On compose the report is the host directory each volume is bind-mounted to.  On the
Kubernetes targets it is the claim's phase and capacity, plus — from the
PersistentVolume it bound to — the storage class, the path on the node, the node itself
where the volume names one, and the reclaim policy:

```
Volumes:
	db-data: Bound (2G)
		PersistentVolume: pvc-fa5a690f-3fa0-4afe-a992-bc19694aa746
		StorageClass: local-path
		Source: local /var/lib/rancher/k3s/storage/pvc-fa5a690f-...-3fa0_stack-9aaaf7e199d5b254_db-data
		Node: test19
		Node affinity: kubernetes.io/hostname In [test19]
		Reclaim policy: Delete
```
