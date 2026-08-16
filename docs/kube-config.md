# Keeping the cluster credential out of the deployment

A Kubernetes deployment needs a kubeconfig, and a deployment directory is a portable
artifact that is frequently a git repository of its own. Copying the kubeconfig into the
deployment therefore means committing a cluster credential to git — usually a
`cluster-admin` one, since that is what `k3s` and most provisioning tools hand you.

The spec's `kube-config` value is a **reference** rather than necessarily a path. It says
where the credential is to be found at the moment it is needed, so the deployment can
record where its credential lives without recording the credential.

## Forms

| Value | Meaning |
| --- | --- |
| `/home/me/.kube/config` | A path. The file is copied into the deployment directory when the deployment is created. |
| `file:/etc/stack/kubeconfig.yml` | A path, read each time the deployer connects. Nothing is copied in. |
| `env:KUBECONFIG_DATA` | The named environment variable holds the kubeconfig **content**. |
| `env-file:KUBECONFIG` | The named environment variable holds a **path** to a kubeconfig. |
| `exec:sops -d cluster.enc.yml` | The command is run and its **stdout** is the kubeconfig. |

A bare path behaves exactly as it always has, so existing specs and deployment directories
are unaffected. Every other form is deferred: the deployment directory gets no
`kubeconfig.yml` at all, the reference travels in `spec.yml`, and it is resolved each time
the deployer connects to the cluster.

A deferred credential is written to a private temporary file for the moment the kubernetes
client takes to read it, and removed immediately afterwards. It is never written into the
deployment directory.

## Setting it

The value is whatever you pass to `stack init --kube-config`, so any of the forms above can
be given there:

```bash
stack init --stack myapp --deploy-to k8s \
  --kube-config env:KUBECONFIG_DATA \
  --image-registry registry.example.com/org \
  --output spec.yml
```

It can equally be set once for a profile — `stack config set kube-config env:KUBECONFIG_DATA`
— or edited in `spec.yml` afterwards, including in the `spec.yml` inside an existing
deployment directory.

The scheme is checked by `init` and `deploy`, so a typo fails at the point you type it. The
credential itself is *not* resolved at that point: the machine that creates a deployment is
often not the machine that connects with it, and requiring the secret to be present at
create time would defeat the purpose.

## In CI

This is the case the `env:` form exists for. A deployment repository built the usual way
requires the job to reconstruct the kubeconfig on disk before it can run anything:

```yaml
      - name: Restore the kubeconfig
        run: echo "${{ secrets.KUBECONFIG }}" > deployment/kubeconfig.yml
      - run: stack manage --dir deployment start
```

That leaves the credential on the runner's disk, inside the deployment, for the life of the
job. With `kube-config: env:KUBECONFIG_DATA` in the spec, the step disappears:

```yaml
      - run: stack manage --dir deployment start
        env:
          KUBECONFIG_DATA: ${{ secrets.KUBECONFIG }}
```

## Reaching a secret store

`exec:` is the general escape hatch, and is how any secret store is reached until it is
worth a scheme of its own. The command runs through a shell, so pipelines work:

```yaml
kube-config: exec:sops -d clusters/prod.enc.yml
kube-config: exec:op read "op://Infrastructure/prod cluster/kubeconfig"
kube-config: exec:pass show clusters/prod
kube-config: exec:vault kv get -field=kubeconfig secret/clusters/prod
```

The command comes from your own spec file, which is the same trust level as the command line
that created it. Note that this cuts both ways: `stack manage` on a deployment repository
cloned from elsewhere will run whatever that repository's `spec.yml` says, so treat a
deployment repository as you would any repository whose build you are about to run.

## What this does and does not solve

It keeps the credential out of the artifact. It does nothing about how much that credential
authorizes, which is the larger exposure: a leaked namespace-scoped, hour-long token is an
incident, and a leaked `cluster-admin` client certificate is a rebuild. Pointing
`kube-config` at a kubeconfig for a ServiceAccount limited to the namespaces `stack` manages
is worth more than any amount of care about where the file is kept.

It also applies only to the credential `stack` itself uses. Secrets a *deployed application*
needs are a separate problem, since those have to reach containers the tool does not own.

## Caveats

A deferred kubeconfig is materialized outside the deployment directory, so if it refers to
certificate files by *relative* path, those paths will not resolve. Embedded (`-data`)
certificates — what `k3s` and every cloud provider emit — are unaffected.
