# stack fetch

Clone repositories and fetch resources

## Synopsis

```bash
stack fetch [OPTIONS] COMMAND [ARGS]...
```

## Description

[Placeholder: Add detailed description of how fetch retrieves repositories and other resources needed for stack deployment]

## Subcommands

### repo

Clone a repository

```bash
stack fetch repo REPO-LOCATOR [OPTIONS]
```

#### Arguments

- `REPO-LOCATOR` (required): Repository identifier in the format `[hostname/]organization/repo[@tag_or_branch]`

#### Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--git-ssh/--no-git-ssh` | FLAG | Use SSH for git rather than HTTPS | From config |
| `--git-pull` | FLAG | Pull the latest changes for an existing repo | False |

## Repository Locator Format

The repository locator has the form `[hostname/]organization/repo[@tag_or_branch]`:

- GitHub shorthand: `owner/repo` (e.g., `bozemanpass/example-todo-list`) — the hostname
  defaults to `github.com`
- Explicit host: `gitea.example.com/owner/repo`
- With a ref: `owner/repo@my-branch`, `owner/repo@v1.2.3`

This is the same locator syntax used by the `repository`, `ref` and `wrapper-ref` fields in
`stack.yml` (see [Stack Files](../stack-files.md)).

Full HTTPS (`https://github.com/owner/repo.git`) and SSH (`git@github.com:owner/repo.git`)
URLs are **not** accepted. Use `--git-ssh` to clone over SSH instead of HTTPS.

### Selecting a branch or tag

The `@tag_or_branch` suffix is the only place a ref is specified for a stack's own
repository. There is no ref argument on `stack build`, `stack prepare` or `stack deploy`:
those commands operate on whatever is currently checked out in the clone.

```bash
# Clone and check out a branch, then build the stack from it
stack fetch repo bozemanpass/example-todo-list@my-branch
stack build containers --stack my-stack
```

`@` accepts anything `git checkout` accepts, so branches and tags both work.

To move an existing clone to a different ref, run `stack fetch repo` again with the new
suffix (the repo is already present, so it is just checked out), or run `git checkout`
directly in the clone directory:

```bash
stack fetch repo bozemanpass/example-todo-list@v1.2.3
```

Note that `--git-pull` is skipped when the repo is on a tag or a detached commit — only
branches are pulled. You will see `skipping pull because this repo is not on a branch`.

If you need two refs of the same stack available at once, clone them to separate
directories yourself and pass the path to `--stack` (see [stack build](build.md)), since a
bare stack name has no ref component and must resolve to exactly one stack.

## Repository Storage

Repositories are cloned to `$STACK_REPO_BASE_DIR`, which defaults to `~/.config/stack/repos`.

Within that directory the layout mirrors the locator: `$STACK_REPO_BASE_DIR/<hostname>/<organization>/<repo>`,
e.g. `~/.config/stack/repos/github.com/bozemanpass/example-todo-list`. That is the working
tree to inspect (or `git checkout` in) when you want to see or change which ref a stack
will be built from.

## Examples

```bash
# Fetch a repository using GitHub shorthand
stack fetch repo bozemanpass/example-todo-list

# Fetch a specific branch
stack fetch repo bozemanpass/example-todo-list@my-branch

# Fetch a specific tag
stack fetch repo bozemanpass/example-todo-list@v1.2.3

# Fetch from a host other than github.com
stack fetch repo gitea.example.com/bozemanpass/example-todo-list

# Fetch using SSH
stack fetch repo bozemanpass/example-todo-list --git-ssh

# Update an existing repository
stack fetch repo bozemanpass/example-todo-list --git-pull

# Fetch with SSH and pull latest
stack fetch repo bozemanpass/example-todo-list --git-ssh --git-pull
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `STACK_REPO_BASE_DIR` | Base directory for cloned repositories |

## See Also

- [stack prepare](prepare.md) - Build or download stack containers
- [stack build](build.md) - Build stack components
