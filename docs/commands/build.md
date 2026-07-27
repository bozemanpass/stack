# stack build

Build stack components (containers, etc.)

## Synopsis

```bash
stack build [OPTIONS] COMMAND [ARGS]...
```

## Description

[Placeholder: Add detailed description of the build command and its purpose in building stack components]

## Subcommands

### containers

Build stack containers

```bash
stack build containers [OPTIONS]
```

#### Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--stack` | TEXT | Name or path of the stack | - |
| `--include` | TEXT | Only build these containers (can be used multiple times) | - |
| `--exclude` | TEXT | Don't build these containers (can be used multiple times) | - |
| `--git-ssh/--no-git-ssh` | FLAG | Use SSH for git rather than HTTPS | From config |
| `--build-policy` | CHOICE | Build policy to use | `as-needed` |
| `--extra-build-args` | TEXT | Supply extra arguments to build | - |
| `--dont-pull-images` | FLAG | Don't pull remote images | False |
| `--publish-images` | FLAG | Publish the built images | False |
| `--image-registry` | TEXT | Specify the remote image registry | From config |
| `--target-arch` | TEXT | Specify a target architecture (only for use with --dont-pull-images) | - |

##### Specifying the Stack

`--stack` accepts either:

- a filesystem path to a directory containing a `stack.yml`, or
- a bare stack name, which is matched against the `name` of every stack found beneath
  `$STACK_REPO_BASE_DIR`. The name must match exactly one stack.

A stack name has **no** branch or tag component — there is no `--stack name@branch` form.
The build uses whatever ref is currently checked out in the cloned repository, so select
the branch or tag when you fetch:

```bash
stack fetch repo bozemanpass/example-todo-list@my-branch
stack build containers --stack my-stack
```

See [stack fetch](fetch.md) for the locator syntax and for how to move an existing clone to
a different ref. If you need to build two refs of the same stack side by side, clone them
into separate directories and pass the paths to `--stack`.

Note that the `@tag_or_branch` suffixes appearing inside `stack.yml` (`repository`, `ref`,
`wrapper-ref`) pin the repositories that individual *containers* are built from; they do not
affect which ref of the stack's own repository is used.

##### Build Policies

Available build policies:
- `as-needed`: Build only if necessary
- `build`: Always build
- `build-force`: Force rebuild
- `prebuilt`: Use prebuilt images
- `prebuilt-local`: Use local prebuilt images
- `prebuilt-remote`: Use remote prebuilt images

## Examples

```bash
# Build all containers for a stack
stack build containers --stack my-stack

# Build specific containers only
stack build containers --stack my-stack --include frontend --include backend

# Force rebuild all containers
stack build containers --stack my-stack --build-policy build-force

# Build and publish to registry
stack build containers --stack my-stack --publish-images --image-registry registry.example.com
```

## See Also

- [stack prepare](prepare.md) - Build or download stack containers
- [stack deploy](deploy.md) - Deploy a stack
