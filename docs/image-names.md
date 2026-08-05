# Container Image Names and Tags

This document describes, in one place, every scheme stack uses for container
image names and tags, and the lifecycle of an image name from the stack
definition through build, publish, and deployment. Related documents:
[stack-files.md](stack-files.md) (where names are declared),
[fetching-containers.md](fetching-containers.md) (how prebuilt images are
discovered and pulled).

## Design goals

Two separations of concern drive the naming schemes:

1. **Structure vs. versions.** A stack or pod file describes the *shape* of a
   system — which containers exist and how they connect — and should not need
   to embed exact image versions. Pod files therefore name images with a
   placeholder tag, and the tooling substitutes a real version at the
   appropriate time.

2. **Source ↔ image binding.** An image is fully determined by the git
   repository (and commit) holding its build recipe. Both the fully-qualified
   image name and the tag are *derived* from the repository reference, so
   given a repo ref, stack can compute where the corresponding image lives
   without any extra configuration — and vice versa.

## The three name forms

An image for a container named `exampleorg/myapp` appears in three forms over
its life:

| Form | Example | Where it appears |
|---|---|---|
| Local placeholder | `exampleorg/myapp:stack` (legacy alias `:local`) | pod/compose files, local docker daemon after build or prepare |
| Canonical (publishable) | `ghcr.io/exampleorg/myapp:<recipe-commit-hash>` | remote registries; produced by `--publish-images`, consumed by `prepare` |
| Deployment-private | `<image-registry>/exampleorg/myapp:deploy-<id>` (k8s) or `exampleorg/myapp:stack-<cluster>` (compose) | generated deployment artifacts |

### The container name

The container `name:` declared in `stack.yml` / `container.yml` is the base
image name. It must include the registry namespace under which the image is
published (for GitHub/ghcr, the GitHub organization) — e.g.
`exampleorg/myapp`, not just `myapp`. The canonical form is produced by
prefixing the registry host, never by rewriting the name itself.

### The placeholder tag `stack`

`<name>:stack` means "the image for this container, as built or prepared on
this machine." It is what pod files reference (`image: exampleorg/myapp:stack`)
and it is only meaningful to the local docker daemon: every build or pull path
ends by tagging its result as `<name>:stack` (and the legacy `<name>:local`).
It is never pushed and never resolvable from a registry; any process that
needs to pull must first translate it to one of the other two forms.

## Canonical names: derived from the recipe repo

### Registry from the git host

`image_registry_for_repo()` (`src/stack/repos/repo_util.py`) maps the recipe
repository's git host to its image registry:

| Git host | Image registry |
|---|---|
| `github.com` | `ghcr.io` |
| `gitlab.com` | `registry.gitlab.com` |
| `bitbucket.org` | `crg.apkg.io` |
| anything else | the host itself |

### Tag from the commit hash

The tag is the commit hash of the **recipe repo** — the repository holding
the container build recipe (see `ImageIdentity` in
`src/stack/build/build_util.py`). Lock files committed in the recipe repo pin
all other build inputs (payload source, wrapper), so the recipe commit alone
identifies the image content.

If the recipe checkout is dirty, or the build used unpinned/deviating inputs,
the version becomes `stackdev-<sha1 of the actual inputs>` instead. `stackdev-`
versions are never published — they identify a local development build only.

So the full canonical reference is:

```
<registry-for-git-host>/<container name>:<recipe repo commit hash>
e.g.  ghcr.io/exampleorg/myapp:0badc0ffee...
```

Given only the stack definition (which carries the repo refs), stack can
compute this reference — this is what lets `prepare` find prebuilt images
with no configuration.

## Lifecycle of an image name

### 1. Authoring

`stack.yml`/`container.yml` declare `name: exampleorg/myapp`; the pod compose
file references `image: exampleorg/myapp:stack`.

### 2. `stack prepare` / `stack build containers`

For each container in scope (`src/stack/build/build_containers.py`):

1. Compute the `ImageIdentity` → expected tag `exampleorg/myapp:<hash>`.
2. If that tag exists locally, use it.
3. Otherwise (per the build policy) look for it remotely, checking in order:
   the `--image-registry` override, then the canonical registry derived from
   the recipe repo. If found, `docker pull <registry>/exampleorg/myapp:<hash>`.
4. Otherwise build it.
5. In every case, cross-tag the result so that `exampleorg/myapp:<hash>`,
   `exampleorg/myapp:stack`, and `exampleorg/myapp:local` all point at the
   same image locally.

With `--publish-images`, the image is additionally pushed as
`<registry>/exampleorg/myapp:<hash>` (refused for `stackdev-` versions).

### 3. `stack init`

Generates the deployment spec. For k8s targets only, `--image-registry <url>`
is recorded in the spec (`image-registry:` key). This designates a *private
staging registry* used to carry locally-built images to the cluster; it is
unrelated to the canonical registry derivation above. If omitted for a `k8s`
target, locally-built images are deployable only if they are published to a
registry the cluster can reach (see step 5), and `init` warns accordingly.

### 4. `stack deploy create`

- **compose target:** each `image: <name>:stack` in the generated compose
  files is rewritten to `<name>:stack-<cluster-id>` so that concurrent
  deployments on one host don't share a mutable tag. At every `up` the local
  `<name>:stack` image is retagged to match whenever the two names resolve to
  different images, so a rebuild is picked up by a restart (erroring with "did
  you run stack prepare?" when neither name exists locally).
- **k8s targets:** pod files keep `<name>:stack`; translation happens at
  manifest-generation time (next step).

### 5. k8s deployment (`cluster_info.py` + `images.py`)

At manifest-generation time, each image reference is resolved per image
(`resolve_image_for_deployment`):

1. **Not a locally-built tag** (e.g. an explicit upstream image like
   `postgres:16`): passed through untouched, pulled exactly as the pod file
   names it.
2. **Locally-built tag (`:stack`/`:local`), staging registry configured**:
   rewritten to the deployment-private staging name

   ```
   exampleorg/myapp:stack  →  <image-registry>/exampleorg/myapp:deploy-<last 8 of deployment id>
   ```

   (registry host replaced, org namespace kept). `stack manage --dir <dir>
   push-images` performs the matching upload: it tags every locally-built
   image with exactly that name and pushes it to the staging registry.
3. **Locally-built tag, no staging registry**: the published canonical
   reference is used. `prepare` and `--publish-images` leave the answer in
   the local docker daemon's tags — a pulled or published image carries
   `ghcr.io/exampleorg/myapp:<hash>` alongside the `exampleorg/myapp:<hash>`
   and `:stack` cross-tags — so the resolver inspects the local image and
   uses the registry-qualified sibling tag whose version matches. The
   cluster then pulls directly from the canonical registry.
4. **Neither available** (built locally, unpublished, no staging registry):
   the deployment cannot work, so manifest generation fails immediately with
   the remedy, instead of the cluster reporting `ImagePullBackOff` later.

Exception: a **kind** deployment with no staging registry loads local images
directly into the kind cluster, so the local reference is used as-is.

The generated pod specs reference an image pull secret named
`stack-image-registry`. Stack assumes registry credentials (for the staging
registry and/or the canonical registries) are configured on the target
cluster out of band, at cluster-configuration time.

## Known gaps

- Only one pull secret name (`stack-image-registry`) is referenced, and it is
  referenced unconditionally — deployments that pull only from public
  registries see a harmless but noisy `FailedToRetrieveImagePullSecret`
  warning on every pod.
- When an image is both published canonically and staged, the staging
  registry wins; there is no per-deployment switch to prefer the canonical
  reference while still configuring a staging registry for other images.
- Deployment-private staging tags (`deploy-<id>`) accumulate in the staging
  registry; nothing cleans them up when a deployment is destroyed.
