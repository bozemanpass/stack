# stack prepare

Build or download stack containers

## Synopsis

```bash
stack prepare [OPTIONS]
```

## Description

[Placeholder: Add detailed description of how prepare orchestrates the building and downloading of containers needed for a stack]

## Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--stack` | TEXT | Name or path of the stack | - |
| `--include-containers` | TEXT | Only build/download these containers (multiple) | - |
| `--exclude-containers` | TEXT | Don't build/download these containers (multiple) | - |
| `--include-repos` | TEXT | Only clone these repositories (multiple) | - |
| `--exclude-repos` | TEXT | Don't clone these repositories (multiple) | - |
| `--git-ssh/--no-git-ssh` | FLAG | Use SSH for git rather than HTTPS | From config |
| `--git-pull` | FLAG | Pull the latest changes for an existing repo | False |
| `--build-policy` | CHOICE | Build policy to use | `as-needed` |
| `--extra-build-args` | TEXT | Supply extra arguments to build | - |
| `--dont-pull-images` | FLAG | Don't pull remote images | False |
| `--publish-images` | FLAG | Publish the built images | False |
| `--image-registry` | TEXT | Specify the remote image registry | From config |
| `--target-arch` | TEXT | Specify a target architecture (with --dont-pull-images) | - |

## Build Policies

| Policy | Description | Use Case |
|--------|-------------|----------|
| `as-needed` | Build only if image doesn't exist or source changed | Default, efficient |
| `build` | Always build from source | Force rebuild |
| `build-force` | Force rebuild, ignore cache | Clean rebuild |
| `prebuilt` | Use prebuilt images only | Production |
| `prebuilt-local` | Use local prebuilt images | Offline work |
| `prebuilt-remote` | Pull from remote registry | CI/CD |
| `fetch-repos` | Only clone repositories, no building | Repository setup |

## Workflow

The prepare command:
1. Clones required repositories (if needed)
2. Builds container images from source (based on policy)
3. Downloads prebuilt images (if specified)
4. Tags images appropriately
5. Optionally publishes to registry

## Examples

### Basic Usage

```bash
# Prepare all containers for a stack
stack prepare --stack my-stack

# Prepare with latest code
stack prepare --stack my-stack --git-pull

# Prepare and publish
stack prepare --stack my-stack --publish-images --image-registry registry.example.com
```

### Selective Preparation

```bash
# Only prepare specific containers
stack prepare --stack my-stack --include-containers frontend --include-containers backend

# Exclude certain containers
stack prepare --stack my-stack --exclude-containers test-utils

# Only clone repositories
stack prepare --stack my-stack --build-policy fetch-repos
```

### Build Policies

```bash
# Force rebuild everything
stack prepare --stack my-stack --build-policy build-force

# Use only prebuilt images
stack prepare --stack my-stack --build-policy prebuilt

# Pull from remote registry
stack prepare --stack my-stack --build-policy prebuilt-remote
```

### Advanced Options

```bash
# Prepare with custom build arguments
stack prepare --stack my-stack --extra-build-args "--build-arg VERSION=1.2.3"

# Prepare for specific architecture
stack prepare --stack my-stack --target-arch arm64 --dont-pull-images

# Prepare with SSH for private repos
stack prepare --stack my-stack --git-ssh --include-repos private-repo
```

## See Also

- [stack build](build.md) - Build stack components
- [stack fetch](fetch.md) - Clone repositories
- [stack deploy](deploy.md) - Deploy a stack
