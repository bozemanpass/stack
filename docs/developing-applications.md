# Developing an Application with `stack`

Most of this documentation describes deploying a stack whose containers are built from
committed, published source. This page covers the other half of the day: you are *editing*
the application — changing the front end, fixing the API — and you want each edit to show up
in a running deployment, locally or on a real cluster, without committing and pushing first.

The short version: point `stack` at your own checkout, build with an explicit build policy,
and know how each deployment target picks up a new image. The examples use
[example-todo-list](https://github.com/bozemanpass/example-todo-list), whose
`stacks/todo/stack.yml` declares two wrapped containers built from the same repo:

```yaml
containers:
  - name: bozemanpass/todo-frontend
    wrapper: webapp
    content-root: frontend
  - name: bozemanpass/todo-backend
    wrapper: node-service
    content-root: backend
```

## 1. Build from your working tree

Normally `stack` clones every repo a stack needs into the dev root
(`STACK_REPO_BASE_DIR`, default `~/.config/stack/repos`) and builds from those clones. That is
the wrong tree to develop in: `--git-pull` may move it under you, and it is not where your
editor, branches, or IDE are pointed.

Instead, identify the stack by **path** into your own checkout:

```bash
STACK=~/projects/example-todo-list/stacks/todo
```

When a stack is loaded from a git checkout that is not the dev-root clone of its repo,
`Stack.repo_is_local_checkout()` reports true, and two things follow:

- the stack's repo is never cloned or pulled — your tree is left exactly as you left it; and
- every container whose source *is* that repo builds with **your working tree as the build
  context**.

The second point covers containers that name no `ref:` (both of the containers above), plus
any container whose `ref:` resolves to the stack's own repo. A container that names some
*other* repo still builds from the dev-root clone of that repo, as usual — the local-checkout
rule applies to the tree you are developing in, not to the stack's dependencies.

`content-root:` then narrows what is built: `frontend` for the front end image, `backend` for
the API. Editing `frontend/src/App.tsx` changes only `bozemanpass/todo-frontend`.

## 2. Build with an explicit build policy

```bash
stack prepare --stack $STACK --build-policy build
```

`--build-policy build` is not optional politeness here; the default `as-needed` policy will
sometimes ignore your edits. To see why, recall how an image is identified
([image-names.md](image-names.md)): the tag is the recipe repo's commit hash when the checkout
is clean, and `stackdev-<hash of HEAD + the diff>` when it is dirty. Under `as-needed`,
`prepare` reuses a matching local image or pulls a matching published one, and only builds if
neither exists.

That is exactly right for a clean tree and exactly wrong for a dirty one, because "dirty" is
narrower than it sounds:

- **Untracked files do not count.** The dirtiness check ignores untracked files, so a
  brand-new component you have not `git add`ed leaves the tree "clean" — the expected tag is
  the plain commit hash, and `as-needed` will happily pull the published image for that commit
  from ghcr and deploy it in place of your work.
- **Only unstaged changes feed the hash.** The `stackdev-` hash is computed from `git diff`,
  i.e. tracked-but-unstaged modifications. Once you `git add` an edit it drops out of that
  diff, so *every* staged-only state of a given commit produces the same `stackdev-` tag,
  whatever the staged content is — and `as-needed` will reuse whichever image was built first
  under that tag.

`--build-policy build` skips the reuse-or-pull branch entirely and always builds.
`--build-policy build-force` additionally builds without the container layer cache — reach for
it when a build step caches something it should not have.

Rebuild only what you touched:

```bash
stack prepare --stack $STACK --build-policy build \
    --include-containers bozemanpass/todo-frontend
```

Either way the result is tagged `bozemanpass/todo-frontend:stack` locally, which is the name
every deployment consumes.

## 3. The local loop (compose)

Create the deployment once:

```bash
stack init --stack $STACK --output spec.yml --deploy-to compose --map-ports-to-host localhost-same
stack deploy --spec-file spec.yml --deployment-dir ~/deployments/todo
stack manage --dir ~/deployments/todo start
```

Then, per edit:

```bash
stack prepare --stack $STACK --build-policy build --include-containers bozemanpass/todo-frontend
stack manage --dir ~/deployments/todo stop
stack manage --dir ~/deployments/todo start
```

### What `start` does with the image

`deploy` rewrites each `image: <name>:stack` in the generated compose files to
`<name>:<cluster-id>` (e.g. `bozemanpass/todo-frontend:stack-99544d5a11a0556e`) so that
concurrent deployments on one host do not share a mutable tag. That deployment-private tag is
(re)pointed at the current `:stack` image on every `start`, so a rebuild is picked up by a
stop/start with no tag housekeeping on your part — you will see

```
Tagging bozemanpass/todo-frontend:stack to bozemanpass/todo-frontend:stack-99544d5a11a0556e...
```

in the `start` output whenever the image has actually changed, and nothing when it has not.

Note that `manage reload` is a `compose restart`, which reuses the existing containers and so
does *not* pick up a new image; use `stop` then `start`.

## 4. The `k8s-kind` loop

`--deploy-to k8s-kind` needs no registry: local images are copied into the kind cluster on
every `up`, so the loop is just

```bash
stack prepare --stack $STACK --build-policy build
stack manage --dir ~/deployments/todo-kind stop
stack manage --dir ~/deployments/todo-kind start
```

with no tag surgery. Use it to check the Kubernetes *shape* of a deployment — pods, volumes,
ingress — without a real cluster.

## 5. The remote Kubernetes loop

A remote cluster cannot see your local docker daemon, so the image has to travel through a
registry. `--publish-images` is not the mechanism: it deliberately refuses `stackdev-`
versions, because those images correspond to no commit and must never occupy a canonical,
reproducible-looking tag.

The mechanism is the deployment's **staging registry**, configured at `init` time:

```bash
stack init --stack $STACK --output k8s-spec.yml --deploy-to k8s \
    --image-registry ghcr.io/bozemanpass \
    --http-proxy-fqdn todo.example.com --http-proxy-target todo-list:3000
stack deploy --spec-file k8s-spec.yml --deployment-dir ~/deployments/todo-k8s
```

`stack manage --dir ... push-images` tags whatever `:stack` currently points at as
`<registry>/<name>:deploy-<last 8 of the deployment id>` and pushes it; manifest generation
rewrites the pod images to exactly that reference. The tag is per-*deployment*, not
per-*build*, so it does not care whether the image is a `stackdev-` build — which is what
makes this the right path for uncommitted work.

(An image that is already published to its canonical registry is pulled from there instead,
and `push-images` skips it. That never applies to the `stackdev-` images this loop produces,
so the loop below is unaffected — but it does mean a stack's untouched, prebuilt containers
are not copied into the staging registry just to be deployed.)

Per edit:

```bash
stack prepare --stack $STACK --build-policy build
stack manage --dir ~/deployments/todo-k8s push-images
stack manage --dir ~/deployments/todo-k8s stop
stack manage --dir ~/deployments/todo-k8s start
```

Non-kind Kubernetes deployments are generated with `imagePullPolicy: Always`, so restarting
re-pulls the (unchanged) `deploy-<id>` tag and gets the new content. No local tag needs
removing, unlike the compose case.

You need push access to the registry (`docker login`) and the cluster needs pull access —
`stack` assumes credentials are configured on the cluster out of band, under the pull secret
name `stack-image-registry`. See [image-names.md](image-names.md) for the full resolution
order.

## 6. Landing the change

Everything above produces `stackdev-` images: unpublishable by construction, and correctly so
— they cannot be reproduced from any commit. Once the work is committed and pushed, the tree
is clean again, the expected tag becomes the recipe repo's commit hash, and the normal
machinery takes over:

```bash
stack prepare --stack $STACK --build-policy build --publish-images --image-registry ghcr.io/bozemanpass
```

That image *is* reproducible from a commit, so a deployment elsewhere can find it with no
staging registry at all — `prepare` on another machine computes the same tag and pulls it.
If the build wrote or updated lock files (`stack.lock`), commit those too: they are what pins
the remaining build inputs so that the recipe commit alone identifies the image content.

## Summary

| | Source of truth | Gets the new image by |
| --- | --- | --- |
| compose | local `:stack` tag | re-tagging `:<cluster-id>` at `start` |
| `k8s-kind` | local `:stack` tag | image copy into kind on every `start` |
| `k8s` | staging registry | `push-images`, then `imagePullPolicy: Always` on restart |

## See Also

- [image-names.md](image-names.md) — image naming and tagging in full, including `stackdev-`
- [fetching-containers.md](fetching-containers.md) — build policies and prebuilt-image discovery
- [stack-files.md](stack-files.md) — `stack.yml`, `content-root`, and lock files
- [wrappers.md](wrappers.md) — how application source with no container build of its own is packaged
- [from-laptop-to-production.md](from-laptop-to-production.md) — choosing a deployment target
