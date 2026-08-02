# stack check

Dry run of prepare: report what is missing

## Synopsis

```bash
stack check [OPTIONS]
```

## Description

Reports what [`stack prepare`](prepare.md) would still have to fetch or build,
without doing any of it.

This is a question about the *build* inputs of a stack, not about a running
deployment — it inspects repos and container images on disk, and never starts,
stops or contacts a deployment. To ask about running containers, use
[`stack manage status`](manage.md#status) instead.

It is most useful when some time has passed since you ran `stack prepare` and
you no longer remember whether it finished. Re-running `prepare` would answer
the question too, but if images are in fact missing it may build for several
minutes; `check` answers immediately.

For each repo and container image the stack requires, one status is reported:

| Status | Meaning |
|--------|---------|
| `ready` | The image is present locally; nothing to do. |
| `available from <registry>` | Not local, but can be pulled by `stack prepare`. |
| `needs built` | Not local and not available remotely; `stack prepare` must build it. |
| `repo needs fetched` | A required stack repo is not present; `stack fetch` must clone it. |

If every item is `ready`, `check` prints a confirmation. Otherwise it names the
`stack prepare` command that would resolve the gaps.

## Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--stack` | TEXT | Name or path of the stack | - |
| `--image-registry` | TEXT | Container image registry URL for this k8s cluster | From config |
| `--git-ssh/--no-git-ssh` | FLAG | Use SSH for git rather than HTTPS | From config |

## Exit Codes

- `0`: Everything the stack needs is already in place
- `1`: One or more repos or images still need to be fetched or built
- `2`: Error occurred during check

## Examples

```bash
# Report anything still missing before deploying
stack check --stack my-stack

# Check with specific registry
stack check --stack my-stack --image-registry registry.example.com

# Check using git SSH
stack check --stack my-stack --git-ssh
```

## See Also

- [stack prepare](prepare.md) - Build or download the containers `check` reports on
- [stack fetch](fetch.md) - Clone the repos `check` reports as missing
- [stack manage status](manage.md#status) - Report status of a *running* deployment
- [stack list](list.md) - List available stacks
