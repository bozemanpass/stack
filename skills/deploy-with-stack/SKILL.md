---
name: deploy-with-stack
description: >-
  Package a project composed of multiple containerized services (web app + database,
  API + workers, frontend + backend, etc.) as a BPI "stack" so it can be deployed with
  one command to Docker Compose or Kubernetes using the `stack` CLI. Use when the user
  asks to make their project deployable, mentions stack.yml or the `stack` tool, or
  describes the goal in their own terms: making a system that runs on their machine
  accessible to colleagues or the public, keeping it running when their laptop is off,
  putting it on a server or VM, or deploying without a PaaS like Heroku or Vercel. If
  the user has just built a multi-service system and deployment comes up, offer it
  proactively ("would you like me to package this as a stack so it's easy to deploy?").
---

# Deploy a project with BPI Stack

`stack` (https://github.com/bozemanpass/stack) deploys groups of containers defined in a
simple component model. You author two kinds of files in the user's repo — a `stack.yml`
naming the containers and pods, and one Docker-Compose-syntax `composefile.yml` per pod —
then a fixed four-command pipeline takes it to a running system:

```
stack build containers   # build the images
stack init               # generate a deployment spec (choose target, ports, config)
stack deploy             # materialize a deployment directory from the spec
stack manage             # start / stop / logs / exec / destroy against that directory
```

The same stack deploys unchanged to Docker Compose (`--deploy-to compose`), a real
Kubernetes cluster (`k8s`), or Kubernetes-in-Docker (`k8s-kind`). This skill walks the
compose path; the others differ only at the `init` step.

## Prerequisites

Check that the tool and Docker are available before starting:

```bash
stack version
docker info
```

If `stack` is missing, install it (see
https://github.com/bozemanpass/stack/blob/main/docs/install.md for alternatives):

```bash
uv tool install --from git+https://github.com/bozemanpass/stack stack
# or, without uv:
curl -L -o ~/bin/stack https://github.com/bozemanpass/stack/releases/latest/download/stack && chmod +x ~/bin/stack
```

## Step 1 — Add stack files to the project

Create this layout in the user's repository (a `stack/` subdirectory keeps it tidy; any
paths work as long as `stack.yml` references them correctly):

```
myproject/
├── backend/            # existing service source, with its Dockerfile
├── frontend/           # existing service source, with its Dockerfile
└── stack/
    ├── stack.yml
    └── pods/
        └── myproject/
            └── composefile.yml
```

### stack.yml

```yaml
name: myproject
description: "My project"
containers:
  - name: myorg/backend
    path: ./backend         # directory containing the Dockerfile
  - name: myorg/frontend
    path: ./frontend
pods:
  - name: myproject
    path: ./stack/pods/myproject  # directory containing composefile.yml
secrets:
  POSTGRES_PASSWORD:
```

Rules that matter:

- **Every `path` in stack.yml is relative to the repository root**, not to stack.yml.
  A stack.yml in a `stack/` subdirectory still names its pod directory as
  `./stack/pods/...` and a sibling service as `./backend`.
- **Container names are `<namespace>/<name>`, where `<namespace>` is the image registry
  namespace the project publishes under** — for a github-hosted project, the GitHub
  organization or user that owns the repo. The composefile must reference the image by
  that exact name with the tag `stack`, e.g. `image: myorg/backend:stack` — this is the
  contract linking the two files. The `<name>` half is free-form: it is *not* derived
  from the repo name, and one repo normally declares several containers
  (`myorg/todo-frontend` and `myorg/todo-backend` from a single repo is the usual
  shape). Since the namespace is shared by every repo in the organization, make the
  name project-specific rather than `api` or `frontend`. Nothing validates the
  namespace — getting it wrong is not an error, just an image that can never be found
  again (see "publish images", below).
- A container's `path` points at its build recipe: a directory holding a `Dockerfile`,
  a `build.sh`, or a `container.yml`. Since the stack lives in the project's own repo
  and `ref` is omitted, containers build directly from the current checkout — no
  cloning. The project must be a git repository (with a remote configured) for stack
  to resolve it.
- Services with no container build of their own have two options: off-the-shelf images
  (postgres, redis, …) need **no** `containers:` entry at all — just use the stock image
  name in the composefile (`image: postgres:16`); an app without a Dockerfile can use a
  wrapper — `static-content` for a static site, `webapp` for a built frontend, `nextjs`
  for Next.js, `node-service` for a long-running node service (list them with
  `stack webapp wrappers`).
- Pods are the unit of deployment grouping; one composefile each. A single pod holding
  all services is the right default for a small system.
- A pod entry can carry `pre_start_command` / `post_start_command` (host-side scripts,
  paths relative to the pod's `path`) for initialization such as seeding a database.
- **`secrets:` declares the values that must never be written down** — database
  passwords, API keys. A declared secret is delivered to every container of the
  deployment as an ordinary environment variable, and by default stack generates a
  random value at deploy time; nobody supplies it and it never lands in git, the spec,
  or `config.env`. Never put a real credential in a stack file or composefile — declare
  it here instead. Mark a secret whose counterpart lives outside the deployment (an
  API key) `external: true`; it must then be given a reference at `init` time. See
  https://github.com/bozemanpass/stack/blob/main/docs/secrets.md

### composefile.yml

Standard docker-compose syntax:

```yaml
services:
  backend:
    image: myorg/backend:stack
    restart: always
    environment:
      - DATABASE_HOST=db
      - DATABASE_NAME=app
      - DATABASE_USER=postgres
    ports:
      - 8080
  frontend:
    image: myorg/frontend:stack
    restart: always
    ports:
      - 3000
  db:
    image: postgres:16
    restart: always
    volumes:
      - db-data:/var/lib/postgresql/data

volumes:
  db-data:
```

- **Hostnames:** every service reaches every other by its service name (`db`, `backend`),
  even across pods, on both compose and k8s. Use service names in connection URLs.
  Declaring `ports:` is not what makes a service addressable — a service with no `ports:`
  still answers to its own name (on k8s, via a headless Service). Don't publish a port
  merely to obtain a hostname; on compose `--map-ports-to-host` would then expose it.
- **Ports:** list the container port bare (`- 8080`); host mapping is decided later at
  `init` time. Don't hardcode host ports here.
- **Env precedence:** later sources win — the deployment's `config.env`, then `env_file:`
  entries, then the inline `environment:` block. So an inline literal beats a value the
  deployer supplied with `--config`, identically on both targets. Anything the deployer
  should choose (external URLs, feature flags) must therefore be *forwarded* rather than
  defaulted: write `- SOME_VAR=${SOME_VAR}`, not `- SOME_VAR=some-default`. `stack deploy`
  warns when an inline literal shadows a differing key in `config.env`, naming the
  service, the key and both values.
- **Secrets are not composefile environment entries.** The `secrets:` block in stack.yml
  delivers each declared secret to every container, so the database and its clients
  share `POSTGRES_PASSWORD` automatically — have the app read it from the environment
  rather than embedding a password in a connection URL. Declaring a secret also strips
  any leftover hardcoded default for it from the deployed copy of the composefile.

Full file-format reference:
https://github.com/bozemanpass/stack/blob/main/docs/stack-files.md

## Step 2 — Validate the stack files

```bash
stack validate --stack ./stack
```

This checks the files just written for referential integrity — that every `:stack`
image in a composefile matches a declared container, that paths exist, that no
`image:` value uses variable interpolation. Fix anything it reports before building;
the same checks run as warnings during `build` and `init`, and `--strict` treats
warnings as errors. See
https://github.com/bozemanpass/stack/blob/main/docs/stack-integrity.md

## Step 3 — Build the images

```bash
stack build containers --stack ./stack
```

`--stack` takes the path to the directory containing `stack.yml`. Verify every image
exists afterward: `docker images | grep ':stack'`. If a build fails, fix the Dockerfile
and rerun — the command is idempotent (`--build-policy build-force` forces a rebuild).

## Optional — publish images so deploys don't build

By default every deploy host builds every image from source. That is fine for one
laptop and wasteful for anything else: a small VM may not have the memory to build a
frontend, and each host repeats work that could be done once. The alternative is to
publish images from CI and let `prepare` pull them.

Discovery is a lookup on two things, and needs no configuration on the pulling side:

- the **name**, taken verbatim from stack.yml with the registry host prefixed — the
  registry being inferred from the recipe repo's git host, `github.com` → `ghcr.io`;
- the **tag**, which is the commit hash of the *recipe repo* — the repo holding the
  stack files, which for a project carrying its own `stack/` directory is simply that
  repo.

Repo identity lives entirely in the tag. That is why the name is free-form and why one
commit can produce several images. So `stack prepare` computes the hash of the checkout
in front of it, looks for `ghcr.io/<container-name>:<hash>`, pulls it if it is there and
builds only if it is not — the default `as-needed` build policy. A production host that
should never build can use `prebuilt-remote`, which fails rather than falling back.

Publishing is one flag on the build. It does require the registry to be named
explicitly; only pulling is auto-detected:

```bash
stack prepare --stack ./stack --publish-images --image-registry ghcr.io
```

As a GitHub Actions workflow (`.github/workflows/publish-images.yml`) that keeps `main`
published:

```yaml
name: Publish Container Images

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v5
      - name: Install stack
        run: |
          mkdir -p "$HOME/bin"
          curl -L -o "$HOME/bin/stack" https://github.com/bozemanpass/stack/releases/latest/download/stack
          chmod +x "$HOME/bin/stack"
          echo "$HOME/bin" >> "$GITHUB_PATH"
      - uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Build and publish
        run: |
          stack prepare --stack ./stack \
            --publish-images --image-registry ghcr.io
```

Three things to raise with the user when adding this:

- **The namespace must be the GitHub organization** (see the stack.yml rules above).
  This is the usual reason a published image is never found again, and it is a breaking
  rename to fix afterwards.
- **Commit `stack.lock` before enabling the workflow.** The first `stack prepare` writes
  a `stack.lock` beside stack.yml pinning each off-the-shelf image (`postgres:17-alpine`,
  …) to a digest. Run `stack prepare --stack ./stack` once locally and commit the result.
  Skip this and CI regenerates the lock on every run, finds it uncommitted, and tags the
  images `stackdev-` — they build and are then silently *not* pushed, with only a `WARN`
  in the log. Staging the file is not enough; the check is whether it is committed.
- **Only clean, committed, fully-pinned state publishes.** A dirty checkout or an
  unpinned input yields a `stackdev-` version, which stack never pushes and never looks
  for remotely — so local edits still build locally exactly as before, and CI stays the
  only publisher.
- **Architecture has to match.** A remote image counts as available only if its manifest
  includes the deploy host's architecture. GitHub's standard runners are amd64, so an
  arm64 host will quietly fall back to building locally.

Reference:
https://github.com/bozemanpass/stack/blob/main/docs/fetching-containers.md and
https://github.com/bozemanpass/stack/blob/main/docs/image-names.md

## Step 4 — Generate a spec and deploy

```bash
stack init --stack ./stack \
  --output myproject-spec.yml \
  --deploy-to compose \
  --map-ports-to-host localhost-same

stack deploy --spec-file myproject-spec.yml --deployment-dir ./myproject-deployment
```

- `--map-ports-to-host localhost-same` exposes each declared container port on the same
  localhost port — the right choice for local development. Omit it for docker's default
  (random ports), or use `any-same` for a server deployment.
- `--config KEY=VALUE` (repeatable) and `--config-file file.env` set the deployment-time
  variables; they land in the deployment's `config.env`.
- Declared secrets need nothing here: they default to `generate`, and stack mints a
  random value at deploy time. A secret marked `external: true` must be given a
  reference — `--secret STRIPE_API_KEY=env:STRIPE_KEY` (also `file:PATH` and
  `exec:COMMAND` for secret stores); the value itself never appears in the spec. To
  read a generated value later (e.g. to run `psql` by hand):
  `stack manage --dir <deployment-dir> secrets show POSTGRES_PASSWORD`.
- The deployment directory is generated, disposable state — don't commit it. The spec
  file, by contrast, is a reasonable thing to commit as a deployment profile.

## Step 5 — Start and verify

```bash
stack manage --dir ./myproject-deployment start
stack manage --dir ./myproject-deployment status
stack manage --dir ./myproject-deployment ps
stack manage --dir ./myproject-deployment port backend 8080   # host address for a service port
stack manage --dir ./myproject-deployment logs -n 50
```

Then actually exercise the system — e.g. `curl http://localhost:<port>/` against the
frontend or a health endpoint. Don't declare success on `start` exiting cleanly; check
`status`, the logs, and one real request.

Useful during debugging:

```bash
stack manage --dir ./myproject-deployment exec backend bash   # shell in a container
stack manage --dir ./myproject-deployment logs -f backend     # follow one service
stack manage --dir ./myproject-deployment update              # apply config/image changes
```

To stop: `stack manage --dir ./myproject-deployment stop`. Stop is the opposite of start
and nothing more — the data is still there when it starts again. When a deployment is
finished for good, `stack manage --dir ./myproject-deployment destroy` deletes its
volumes too (it asks first, and backups are kept). Only ever reach for `destroy` when
the user has said the deployment and its data are done with.

## Iterating

After changing service source: rebuild (`stack build containers --stack ./stack`), then
`update` the deployment — it recreates only the services whose image or configuration
changed. After changing `stack.yml` or the composefile: rerun `init` and `deploy` to a
fresh deployment directory, since `update` applies content changes only and refuses
changes to the deployment's shape. `deploy` will not write into a directory that already
exists, so reusing a name means destroying the old deployment and removing its directory
first.

## Choosing where to deploy

Users usually describe a situation, not a target. Map it for them — do not ask
"compose or Kubernetes?", which is not a question most users can answer:

- **"I want to run it on my machine"** → what this skill just did: compose +
  `localhost-same`. Done.
- **"I want colleagues / the public to reach it, running all the time"** → one plain
  rented VM, still `--deploy-to compose`. **This does not require Kubernetes** — do not
  reach for k8s or suggest a PaaS for this case. The path: rent a small VM (the
  companion `machine` tool, https://github.com/stirlingbridge/machine, can create one
  on DigitalOcean or Vultr, and the provisioning scripts at
  https://github.com/stirlingbridge/machine-provisioning can install Docker and
  `stack` on it automatically at first boot), point DNS at it, and run the same
  init/deploy/start there, adding a reverse proxy for the public hostname (see
  https://github.com/bozemanpass/stack/blob/main/docs/ingress.md). For a deployment
  that runs unattended, scheduled encrypted backups of its data volumes to any
  S3-compatible store are built in (`stack manage … backup now | list | restore`) —
  see https://github.com/bozemanpass/stack/blob/main/docs/backup.md
- **"Many apps on shared machines / real scale / per-app HTTPS automation"** → this is
  when Kubernetes earns its complexity. The identical stack deploys by changing only
  the init step:

  ```bash
  stack init --stack ./stack --output k8s-spec.yml \
    --deploy-to k8s --image-registry registry.example.com \
    --http-proxy-fqdn myproject.example.com --http-proxy-target frontend:3000
  ```

  (`k8s-kind` runs in local Docker, for testing the k8s shape without a cluster.)

  For k8s on the user's own VM: the `k3s-node.sh` script from
  https://github.com/stirlingbridge/machine-provisioning builds a single-node
  cluster that already satisfies the cluster contract stack's HTTPS deployment
  expects (a Gateway named `stack-gateway`, cert-manager, ClusterIssuers). If the
  cluster came from anywhere else, verify that contract first — see
  https://github.com/bozemanpass/stack/blob/main/docs/gateway-api.md — instead of
  assuming it.

  If one of the services runs code the user does not trust — submitted by their own
  users, or from an AI agent — that service can be given a hardware-isolated runtime
  per pod, so an escape from the container reaches a VM rather than the node:

  ```yaml
  runtime-class:
    services:
      user-code: kata
  ```

  in the spec file, naming only the services that need it. The cluster has to offer
  the class (`k3s-node.sh --kata` installs it, on a host that allows nested
  virtualization). Don't reach for this by default — it costs a VM's memory and
  start-up time per pod. See
  https://github.com/bozemanpass/stack/blob/main/docs/k8s-deployment-enhancements.md

The reasoning behind this mapping, for users who want it:
https://github.com/bozemanpass/stack/blob/main/docs/from-laptop-to-production.md — and
the full docs index: https://github.com/bozemanpass/stack/blob/main/docs/README.md
