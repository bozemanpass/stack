# stack check

Check if stack containers are ready

## Synopsis

```bash
stack check [OPTIONS]
```

## Description

[Placeholder: Add detailed description of how the check command verifies container readiness and health status]

## Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--stack` | TEXT | Name or path of the stack | - |
| `--image-registry` | TEXT | Container image registry URL for this k8s cluster | From config |
| `--git-ssh/--no-git-ssh` | FLAG | Use SSH for git rather than HTTPS | From config |

## Exit Codes

- `0`: All containers are ready
- `1`: One or more containers are not ready
- `2`: Error occurred during check

## Examples

```bash
# Check if all containers in a stack are ready
stack check --stack my-stack

# Check with specific registry
stack check --stack my-stack --image-registry registry.example.com

# Check using git SSH
stack check --stack my-stack --git-ssh
```

## See Also

- [stack manage status](manage.md#status) - Report stack and container status
- [stack list](list.md) - List available stacks
