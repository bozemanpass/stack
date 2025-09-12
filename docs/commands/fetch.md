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

- `REPO-LOCATOR` (required): Repository identifier in format `owner/repo` or full URL

#### Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--git-ssh/--no-git-ssh` | FLAG | Use SSH for git rather than HTTPS | From config |
| `--git-pull` | FLAG | Pull the latest changes for an existing repo | False |

## Repository Locator Format

The repository locator can be specified as:
- GitHub shorthand: `owner/repo` (e.g., `bozemanpass/example-todo-list`)
- Full HTTPS URL: `https://github.com/owner/repo.git`
- Full SSH URL: `git@github.com:owner/repo.git`

## Repository Storage

Repositories are cloned to:
- Default: `$STACK_REPO_BASE_DIR` (if set)
- Otherwise: `~/stack/repositories/`

## Examples

```bash
# Fetch a repository using GitHub shorthand
stack fetch repo bozemanpass/example-todo-list

# Fetch using full HTTPS URL
stack fetch repo https://github.com/bozemanpass/example-todo-list.git

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
