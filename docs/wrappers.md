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
| `node-service`   | `bozemanpass/node-service-base`   | [stack-wrapper-webapp](https://github.com/bozemanpass/stack-wrapper-webapp) |
| `static-content` | `bozemanpass/static-content-base` | [stack-wrapper-static-content](https://github.com/bozemanpass/stack-wrapper-static-content) |

The first three build node.js applications. `webapp` and `nextjs` produce *static content*:
the app is built and a web server in the base image serves the result. `node-service` is
different in kind — the application process is itself the server, so the build keeps
`package.json` and the installed `node_modules` alongside any compiled output, and the
container start command runs the app. A node service also needs no build-time placeholder
for its configuration, because unlike a browser bundle it reads `process.env` directly at
startup.

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
`detect` rules (e.g. a `next` dependency in `package.json` selects `nextjs`, an `express`
dependency selects `node-service`), falling back to the wrapper marked `default`.  Only
`dependencies` are consulted, not `devDependencies`, and the first matching wrapper wins — so
name the wrapper explicitly when an app could match more than one.  See
[webapp.md](./webapp.md) for the full webapp build/run/deploy workflow.

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

## Content root

By default the whole source repository is wrapped: it is the build context for the wrapper's
containerfile, so for `static-content` the repository root becomes the document root.  That
suits a repository that holds nothing but the site.  A repository that also holds a README, CI
config, or its own stack files needs to say which directory is the content:

```
my-static-site/             <- ref
├── README.md
├── stack-files/
│   └── stacks/my-site/stack.yml
└── site/                   <- content-root: this is what gets served
    ├── index.html
    └── pages/about.html
```

```yaml
containers:
  - name: bozemanpass/my-static-site
    ref: myorg/my-static-site
    wrapper: static-content
    content-root: site
```

`http://<host>/pages/about.html` then serves `site/pages/about.html`.  Only the content root is
sent to the container build, so everything outside it is absent from the image entirely — not
merely unreferenced.

The same field works in a repository's own `container.yml`, so a self-describing repo carries
its layout with it:

```yaml
container:
  name: bozemanpass/my-static-site
  wrapper: static-content
  content-root: site
```

and on the command line:

```
$ stack webapp build --wrapper static-content --source-repo ~/my-static-site --content-root site
```

`content-root` is not wrapper-specific: it narrows the build context of an ordinary container
build the same way.  See [stack-files.md](./stack-files.md#path-vs-content-root) for how it
relates to `path`, with worked examples of each combination.

## Runtime environment

A service reads its configuration from the environment at startup, so deploying the same image
to staging and production is just a matter of setting different variables.  A *webapp* cannot
do that: its code runs in a browser, which has no environment, so a bundler resolves every
configuration value at build time and freezes it into the bundle.  Taken at face value that
would mean one image per environment.

The `webapp` and `nextjs` wrappers avoid this by building with a **placeholder** in place of
each value, and rewriting the placeholders when the container starts.  A placeholder is the
variable's name prefixed with `STACK_RUNTIME_ENV_`, so an app configured by `API_URL` is built
as though `API_URL` were the literal string `STACK_RUNTIME_ENV_API_URL`.  At startup
`apply-runtime-env.sh` walks the served files, finds each placeholder, and replaces it with the
value of the correspondingly named environment variable — here, `$API_URL`.  The image itself
stays environment-independent.

Placeholders reach the bundle in one of two ways.

**Automatically, for apps that read `process.env`.**  Before the build, the wrapper scans the
app's `.js`/`.jsx`/`.ts`/`.tsx` sources for `process.env.<NAME>` and exports each one set to its
own placeholder, which the bundler then inlines.  Create React App and webpack-style apps need
no configuration at all.  The scan covers the source root's subdirectories, skipping hidden ones
and any listed in `.gitignore`, so a reference sitting in a file at the very top level is not
picked up.

**By hand, for everything else.**  The scan only recognizes the literal `process.env.<NAME>`
form.  Vite reads configuration as `import.meta.env.VITE_<NAME>`, so nothing matches and no
placeholder is produced — the build silently bakes in whatever the value was at build time.
Such an app sets the placeholder itself, e.g. in `.env.production`:

```
VITE_API_URL=STACK_RUNTIME_ENV_API_URL
```

Vite inlines that literal, and startup substitution rewrites it from `$API_URL` as usual.  Note
the deliberate asymmetry: the build-time variable is the one the framework requires
(`VITE_API_URL`), while the runtime variable is whatever the placeholder names (`API_URL`).

At startup the wrapper rewrites `.htm`, `.html`, `.js`, `.jsx`, `.ts`, `.tsx` and `.json` files
under the served directory, skipping `node_modules` and `.git`.  Substitution happens after
minification and is textual, but it matches whole tokens rather than bare substrings: the
placeholder has to be bounded by whitespace, a quote (including a backtick), or one of
`/ \ { } , ( ) ;`.  Every form a bundler emits a string literal in is covered, so it does not
matter how the build chose to quote it — but a placeholder dropped into free-form markup, as in
`<p>STACK_RUNTIME_ENV_API_URL</p>`, is not recognized.  Put it in an attribute or a script
string instead.

A `.env` file in the served directory is loaded first if present, with real environment
variables taking precedence over it.  Surrounding quotes are stripped from substituted values
unless `STACK_RETAIN_ENV_QUOTES=true`.

Each substitution is logged as `<file>: <NAME>=<value>`.  That log is the thing to check when an
app comes up pointing at the wrong address, because **a placeholder that is never found is not
an error** — the wrapper simply has nothing to do, the unsubstituted string ships to the
browser, and the failure only shows up as a bad request at runtime.

The `node-service` wrapper does none of this, and needs none of it: a node process reads
`process.env` directly when it starts, so ordinary container environment variables already
work.

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
the `wrappers` section of a `stack.lock` file next to the stack.yml (see
[stack-files.md](./stack-files.md#stacklock); it supersedes the earlier `wrapper.lock`).  When
present, the locked commit is checked out when the wrapper repo is freshly cloned — and it
names the exact prebuilt base image to pull — making the build repeatable.  Commit
`stack.lock` to the stack's repo to pin the wrapper version for everyone; remove the lock
entry and rebuild to re-lock at a newer version.

The lock also feeds the image identity: a wrapped container's image tag is the commit hash of
the repo hosting its build declaration, whose committed locks pin the wrapper (and, for a
source repo other than the stack's own, the payload).  Building against a wrapper checkout
that has drifted from the locked hash produces a warning and a `stackdev-` tagged image
rather than one bearing a commit hash that would not reproduce it.

## Prebuilt app images

Wrapped app images can themselves be published and fetched prebuilt, exactly like any other
container image — image discovery does not care how an image was built.  When `stack prepare`
runs with a policy that allows prebuilt images (e.g. the default `as-needed`), it looks for
`<container-name>:<commit-hash>` — where the hash is the current commit of the *recipe repo*,
the repository hosting the stack.yml (or container.yml) that declares the wrapped container —
locally and then in that repo's image registry (ghcr for github-hosted repos), *before* any
wrapper machinery is engaged.  On a hit the image is simply pulled and tagged; the wrapper
repo is not consulted or even fetched.  See [fetching-containers.md](./fetching-containers.md)
for the general discovery rules.

This means the repository carrying the stack files — whether that is the application repo
itself, or a separate stack repo wrapping an application repo it does not control — can
publish the wrapped image from CI, and consumers (in particular k8s deployments) never need
to build it:

```
$ docker login ghcr.io ...
$ stack prepare --stack <path-to-stack> --publish-images --image-registry ghcr.io
```

The publish step pushes `ghcr.io/<container-name>:<commit-hash>` with the same commit hash a
consumer's `stack prepare` will compute, so discovery matches.  Note that the registry must be
given explicitly when pushing (auto-detection applies only to pulls), and the container name in
`stack.yml` must start with the registry organization (e.g. `bozemanpass/my-static-site`).

A publishable identity requires a committed `stack.lock` pinning the wrapper (and the app
source repo, when it is not the stack's own repo).  Anything else — unpinned inputs, an
uncommitted lock file, a dirty recipe or source checkout — produces a synthetic `stackdev-`
tag that is never published and never matched remotely, so such builds fall back to local
images, which is the behavior a developer iterating on the app wants.  The first build
generates the missing lock entries; committing them is what stabilizes the image tag, and
updating the wrapper or ingesting new app content means regenerating the lock, which produces
a new recipe commit and hence a new image tag.

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
  #                                     under `dependencies` (devDependencies are ignored)
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
