# Container Wrappers

A *wrapper* is a recipe for packaging application source from a git repository into a runnable
container image, for applications that do not provide their own container build.  A repository
containing only static HTML, or a Next.js app with no Dockerfile, can be built and deployed by
naming an appropriate wrapper — no containerization knowledge is required of the application
author.

Each wrapper pairs a *base container image* (which carries the runtime, e.g. nginx or node)
with a *containerfile* that builds the application source into a servable image on top of that
base.

## Available wrappers

Wrappers live in their own repositories and are discovered automatically from any repository
fetched beneath the stack repo base directory (`STACK_REPO_BASE_DIR`).  If no suitable wrapper
has been fetched, `stack` fetches the default wrapper repositories itself.

| Wrapper          | Base container                    | Repository |
|------------------|-----------------------------------|------------|
| `webapp`         | `bozemanpass/webapp-base`         | [stack-wrapper-webapp](https://github.com/bozemanpass/stack-wrapper-webapp) |
| `nextjs`         | `bozemanpass/nextjs-base`         | [stack-wrapper-webapp](https://github.com/bozemanpass/stack-wrapper-webapp) |
| `static-content` | `bozemanpass/static-content-base` | [stack-wrapper-static-content](https://github.com/bozemanpass/stack-wrapper-static-content) |

List the wrappers available locally with:

```
$ stack webapp wrappers
```

## Using a wrapper

### Directly, with `stack webapp build`

```
$ stack webapp build --wrapper static-content --source-repo ~/my-static-site
```

If `--wrapper` is omitted the wrapper is auto-detected from the app source using each wrapper's
`detect` rules (e.g. a `next` dependency in `package.json` selects `nextjs`), falling back to
the wrapper marked `default`.  See [webapp.md](./webapp.md) for the full webapp build/run/deploy
workflow.

### In a stack, with the `wrapper` field

A container entry in `stack.yml` may name a wrapper, in which case the referenced repository is
wrapped rather than built:

```yaml
containers:
  - name: bozemanpass/my-static-site
    ref: myorg/my-static-site
    wrapper: static-content
```

The image is built through the normal container pipeline (content-hash tagging, repository
fetching and locking all apply) and is referenced from the pod's composefile like any other
container image, e.g. `image: bozemanpass/my-static-site:stack`.

For a complete working example, see
[stack-test-static-content](https://github.com/bozemanpass/stack-test-static-content) (a
repository containing only static HTML, with no container build files) and the
`test-static-content` stack in
[stack-test-stacks](https://github.com/bozemanpass/stack-test-stacks) that builds and deploys
it via the `static-content` wrapper.

A repository may instead declare its own wrapping in its `container.yml` with the same
`wrapper` field (see [stack-files.md](./stack-files.md)).

## Prebuilt base images

Wrapper repositories publish their base images to a container registry (ghcr for github-hosted
repos) via their own CI, tagged with the commit hash of the wrapper repo that produced them.
When a base image is needed, `stack` first looks for `<base-container>:<wrapper-repo-hash>`
locally, then in the registry, and only builds the base locally when neither is available (or
when the local wrapper repo checkout has uncommitted changes, or `--force-rebuild` is given).

## Pinning and locking wrapper versions

By default the wrapper is used at whatever version has been fetched.  To pin a specific
wrapper repository (or branch/commit), use `wrapper-ref` in stack.yml:

```yaml
containers:
  - name: bozemanpass/my-static-site
    ref: myorg/my-static-site
    wrapper: static-content
    wrapper-ref: bozemanpass/stack-wrapper-static-content@main
```

or `--wrapper-ref` with `stack webapp build`.  This is also useful for testing an unmerged
wrapper branch end to end, since wrapper CI publishes a base image for every pushed commit.

When a wrapped container is built from a stack, the wrapper repo's commit hash is recorded in
a `wrapper.lock` file next to the stack.yml (analogous to `container.lock`).  When present,
the locked commit is checked out when the wrapper repo is freshly cloned — and it names the
exact prebuilt base image to pull — making the build repeatable.  Commit `wrapper.lock` to the
stack's repo to pin the wrapper version for everyone.  A warning is issued if the local
wrapper repo drifts from the locked hash; remove the lock entry to re-lock at a newer version.

## Authoring a wrapper

A wrapper repository contains one directory per wrapper (or a single wrapper at the top level),
each holding:

- `wrapper.yml` — the manifest (below)
- a `Containerfile` for the base image
- a containerfile that wraps the app source (named by the manifest, e.g. `Containerfile.app`)
- `build.sh` — the build script invoked by `stack`
- any runtime scripts baked into the base image

### wrapper.yml

```yaml
wrapper:
  # Short name, used to select the wrapper (required).
  name: nextjs
  description: Next.js webapp with runtime environment variable support
  # The base image name (required).  Built (or pulled) like any container; the app
  # containerfile should build FROM this image with the tag `stack`.
  base-container: bozemanpass/nextjs-base
  # The containerfile used to wrap the app source (required).  The docker build context
  # is the app source repository, not the wrapper directory.
  containerfile: Containerfile.webapp
  # The port the wrapped app serves on.
  port: 80
  # Optional: mark this wrapper as the fallback when auto-detection finds no match.
  default: true
  # Optional: rules for auto-detection from the app source.  Currently supported:
  #   package-json-dependency: <name> — matches if package.json lists the dependency
  detect:
    package-json-dependency: next
```

### The build contract

`build.sh` is executed twice: once to build the base image, and again (with overrides) to build
the wrapped app image.  It should honor these environment variables, falling back to base-image
defaults when they are unset:

| Variable | Base build | App build |
|----------|-----------|-----------|
| `STACK_CONTAINER_BUILD_WORK_DIR` | (unset — use the wrapper directory) | the app source repository |
| `STACK_CONTAINER_BUILD_CONTAINERFILE` | (unset — use the base `Containerfile`) | the manifest's `containerfile` |
| `STACK_CONTAINER_BUILD_TAG` | (unset — use `<base-container>:stack`) | the app image tag |
| `STACK_WEBAPP_BUILD_RUNNING` | (unset) | `true` |

`STACK_CONTAINER_BASE_DIR` points at the stack tool's container-build data directory; build
scripts should `source ${STACK_CONTAINER_BASE_DIR}/build-base.sh` to pick up standard handling
of forced rebuilds and extra build arguments.  See
[stack-wrapper-static-content](https://github.com/bozemanpass/stack-wrapper-static-content) for
a minimal complete example.

A wrapper repository should also provide a CI workflow that publishes its base image(s) to a
registry on every push, named `<registry>/<base-container>` and tagged with the full commit
hash (see `.github/workflows/publish-images.yml` in the existing wrapper repos) — this is what
allows `stack` to pull prebuilt bases instead of building them locally.

The app containerfile builds with the app source repository as its context.  A two-stage build
is recommended so that unwanted files (e.g. `.git`) are excluded from the final image:

```dockerfile
FROM bozemanpass/static-content-base:stack as builder
COPY . /content
RUN rm -rf /content/.git /content/.github

FROM bozemanpass/static-content-base:stack
COPY --from=builder /content /usr/share/nginx/html
```
