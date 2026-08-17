# Secrets a stack's containers need

Most stacks have at least one value that should not be written down: a database
password, an API key. Before this mechanism existed the test database stack, for
example, carried its password in the clear in its compose file — which means in
git, in the copy inside every deployment directory, and in every deployment
directory's `config.env`.

The `secrets` mechanism splits the problem the way the `config` mechanism splits
configuration: the **stack** declares *which* environment variables are secret,
and the **spec** records where each *value* comes from — never the value itself.
The containers see ordinary environment variables either way; nothing about a
stack's application code changes between targets.

## Declaring, in stack.yml

```yaml
name: my-stack
pods:
  - name: db
    path: ./db
secrets:
  POSTGRES_PASSWORD:
  STRIPE_API_KEY:
    external: true
```

A declared secret is a deployment-wide environment variable, delivered to every
container of the deployment exactly as a `config` value is — which is the point
for something like a database password, where the database and its clients need
the same value and neither is special.

The declaration replaces any literal in the compose file: a leftover default
(`POSTGRES_PASSWORD: "password"`) is stripped from the deployment's copy of the
compose file rather than deployed, so declaring the secret is also the migration
path for a stack that used to carry one.

`external: true` says a generated value would be useless because the secret's
counterpart lives outside the deployment (the payment provider knows your API
key; nobody knows a random one). An external secret must be given a reference at
init time.

## Providing values, in the spec

```yaml
secrets:
  POSTGRES_PASSWORD: generate
  STRIPE_API_KEY: env:STRIPE_KEY
```

There are two kinds of entry, and a literal value is refused — the spec travels
in git, so values never sit in it:

- **`generate`** — the default for a declared secret. Stack mints a random value
  at deploy time; nobody supplies it and nobody needs to see it. This is the
  right thing for any credential that only has to match *within* the deployment.
- **a reference** — the same schemes as [`kube-config`](kube-config.md):
  `env:VAR_NAME` (the variable holds the value), `file:PATH`,
  `env-file:VAR_NAME` (the variable holds a path), and `exec:COMMAND` as the
  escape hatch to any secret store (`sops -d …`, `op read …`, `pass show …`).
  References are validated at init and deploy time but resolved only when the
  deployment comes up, so the machine that creates a deployment does not need
  the secret to be present.

They are set with `--secret` at init time:

```bash
stack init --stack my-stack --output spec.yml \
  --secret STRIPE_API_KEY=env:STRIPE_KEY
```

A `--secret` may also name something the stack does not declare, the same way
`--config` accepts arbitrary variables, and may override a declared secret's
default (`--secret POSTGRES_PASSWORD=exec:pass show db` instead of generating).
A key may not appear in both `config` and `secrets`.

## Where values live, per target

The rule is: a secret appears in no artifact — not `spec.yml`, not `config.env`,
not a generated compose file. What differs per target is where a *generated*
value persists, and it follows where the data lives, because a generated
password is typically baked into a data volume and has to live exactly as long
as the volume does:

| Target | Generated values | Referenced values |
| --- | --- | --- |
| `k8s` | Only in the cluster: a Secret named `stack-secrets` in the deployment's namespace, beside the PVCs. Minted at up time, kept on redeploy. | Resolved at each up and written into the same Secret. |
| `k8s-kind` | `secrets.env` in the deployment directory, beside the data the kind node bind-mounts from it — stopping a kind deployment destroys the cluster, so the cluster cannot be the store. The cluster Secret is rebuilt from it at up. | Resolved at each up, into the cluster Secret only. |
| `compose` | `secrets.env` in the deployment directory, read by every service as an env file. | Resolved at each up and passed by compose interpolation; never written to disk. |

On Kubernetes the containers reference the Secret (`valueFrom: secretKeyRef`),
so the values also never appear in the Deployment objects — `kubectl describe
deploy` shows where a value comes from, not what it is.

`secrets.env` is written mode 0600, and a `.gitignore` covering it is written
into the deployment directory, since a deployment directory is frequently a git
repository. Generated values are create-or-keep: bringing a deployment up again
never rotates them.

## Inspecting a deployment's secrets

```bash
stack manage --dir <deployment-dir> secrets list
stack manage --dir <deployment-dir> secrets show [NAME]...
```

`list` prints each secret's name and provenance and reveals nothing. `show`
prints `NAME=value` lines in the clear — it exists because a generated value was
never typed by anyone, so debugging (`psql` against the deployed database, say)
needs a sanctioned way to read it. Values come from wherever the target stores
them: `secrets.env` plus freshly resolved references on compose and kind (no
cluster needed), the `stack-secrets` Secret on a remote cluster.

## What this does and does not solve

It keeps secret values out of the stack's files, the spec, and the deployment
artifacts — the things that get committed and shared. It does not make the
running deployment's secrets unreadable by its operator, and cannot: on compose,
anyone who can talk to the docker daemon can read any container's environment
(`docker inspect`), and on Kubernetes anyone with read access to Secrets in the
namespace can do the same. On a self-managed cluster,
[encrypting Secrets at rest](https://docs.k3s.io/security/secrets-encryption)
closes the remaining gap on the cluster side.

Changing a *referenced* secret's source value takes effect the next time the
deployment comes up (`stop` + `start`, or `update` on Kubernetes); a running
container's environment is never edited in place.
