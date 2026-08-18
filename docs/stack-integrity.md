# What is in a stack, exactly?

A stack is defined across several files — a `stack.yml` and one composefile per pod —
and the question this page answers is how those files relate: which one is
authoritative for what, how the tool checks that they agree, and how every image a
deployment runs gets a locked version.  The `stack validate` command checks all of it,
and the same checks run advisorily (as warnings) during `stack prepare`, `stack build`
and `stack init`.

## The authority model

Each fact about a stack has exactly one home.  Everything else is either derived from
that home or checked against it.

**Pod files are authoritative for what the stack *uses*.**  A service's `image:` line
is an import: it names exactly the image that service runs.  Because it must be usable
verbatim, variable interpolation is not allowed in an `image:` value — an image
reference with a `$` in it is a validation error.

**`containers:` entries are authoritative for how a locally built image is *made*.**
An entry exists to answer "where does this image come from?": the source repo (`ref`),
the recipe location (`path`), a wrapper, a content root.  A container hosted in the
stack's own repo needs nothing but its name — the bare-string shorthand:

```yaml
containers:
  - bozemanpass/test-container
```

The two sides are joined by the image tag.  An image tagged `:stack` (or `:local`) is
a *locally built* image, and its name must match a declared container:

```yaml
# composefile.yml                          # stack.yml
services:                                  containers:
  backend:                                   - name: bozemanpass/todo-backend
    image: bozemanpass/todo-backend:stack        wrapper: node-service
```

Any other tag makes the image *external*: it is pulled exactly as written
(`postgres:14`), and it needs no declaration in `stack.yml` — the pod file's reference
is already the complete statement of what is used.  External images are version-locked
by digest instead; see below.

**Everything else is derived.**  The set of repositories a stack needs is computed
from its container `ref`s (plus the stack's own repo and any wrapper repos); the
version pins live in the lock files.  Two older fields let these facts be stated a
second time by hand, and both are now deprecated:

- The top-level `repos:` list.  It predates container `ref`s and duplicated them;
  today `stack fetch` and `stack prepare` derive the clone set, and a `repos:` entry
  either restates what a container already says or names a repo nothing else refers
  to.  Validation warns on both.
- The per-pod `repository:` field, which took a pod file from a repo other than the
  stack's own.  Borrowing a bare pod file splits usage from provenance: the borrowed
  file imports `:stack` images whose container declarations stay behind in the other
  repo.  The self-consistent unit of reuse is a whole stack — declare the other repo's
  stack under `requires:` instead (a "super stack"; see the example in
  [ingress.md](./ingress.md#combining-stacks)).

## What `stack validate` checks

```bash
stack validate --stack my-stack
```

Errors (exit 1):

| Code | Meaning |
|---|---|
| `container-undeclared` | A pod file imports `name:stack` but `stack.yml` declares no container `name`.  The image can never be built, so a deployment would fail later with a missing image. |
| `pod-file-missing` | A `pods:` entry names no readable composefile. |
| `service-no-image` | A service has no `image:` line. |
| `image-interpolation` | An `image:` value contains `$`. |
| `container-unnamed`, `container-duplicate` | A malformed or repeated `containers:` entry. |

Warnings (exit 0, or 1 with `--strict`):

| Code | Meaning |
|---|---|
| `container-unused` | A declared container that no pod file imports: it would be built for nothing. |
| `external-image-untagged` | An external image with no tag — an implicit, mutable `latest`. |
| `repos-deprecated`, `repo-unreferenced` | The deprecated `repos:` list (see above). |
| `pod-repository-deprecated` | The deprecated per-pod `repository:` field (see above). |
| `required-stack-missing` | A super stack's required stack is not fetched, so it could not be validated. |

A super stack is validated by validating each required stack in isolation: a child
stack must be deployable on its own, so its pod files may only import containers it
declares itself.

`stack validate` is suitable for a stack repo's CI; `--strict` makes warnings fail the
run too.

## External images are locked by digest

A locally built image is already version-locked: its tag is the recipe repo's commit
hash (see [stack-files.md](./stack-files.md#image-identity-and-lock-files)).  External
images get the equivalent through the `images` section of the `stack.lock`:

1. `stack prepare` resolves each external image reference to its manifest digest
   (pulling the image if it is not already local) and records it:

   ```yaml
   # stack.lock
   images:
     postgres:14: sha256:6baf43584bcb78f2e5847d1de515f23499913ac9f12bdf834811a3145eb11ca1
   ```

2. `stack deploy` rewrites the *deployment's copy* of each pod file to the pinned
   form, `postgres@sha256:...`.  The source pod file keeps the readable tag.

   The one exception is the `k8s-kind` target, which deploys the tag as written:
   kind clusters receive images by side-load (`kind load`) rather than by pull,
   and the side-load re-serializes the image, so it can never satisfy a pod spec
   that names the image by its registry digest.  Kind is a local test target, so
   the reproducibility loss is confined to it; `compose` and real `k8s`
   deployments both pull by digest.

Commit the `stack.lock` to make the choice durable — the same rule as every other
lock section.  An existing pin is never silently re-resolved: to move to a newer
upstream image, delete the entry (or the file) and run `stack prepare` again.

To keep an image floating deliberately, annotate its `image:` line:

```yaml
services:
  db:
    image: postgres:14  # @stack unpinned
```

An annotated image is never locked and never rewritten.  The annotation is visible in
review, which is the point: an image that floats should say so, rather than merely
lacking a pin.

## See also

- [stack-files.md](./stack-files.md) — the file formats themselves
- [fetching-containers.md](./fetching-containers.md) — repos, refs and pins at fetch time
- [commands/validate.md](./commands/validate.md) — command reference
