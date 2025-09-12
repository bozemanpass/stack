# stack config

Manage configuration settings for the stack command

## Synopsis

```bash
stack config [OPTIONS] COMMAND [ARGS]...
```

## Description

[Placeholder: Add detailed description of configuration management, profiles, and persistent settings]

## Subcommands

### get

Get the value of a configuration setting

```bash
stack config get KEY
```

#### Arguments

- `KEY` (required): The configuration key to retrieve

### set

Set the value of a configuration setting

```bash
stack config set KEY [VALUE]
```

#### Arguments

- `KEY` (required): The configuration key to set
- `VALUE` (optional): The value to set (if omitted, key is set to empty string)

### unset

Remove a configuration setting

```bash
stack config unset KEY
```

#### Arguments

- `KEY` (required): The configuration key to remove

### show

Show the full configuration

```bash
stack config show
```

## Configuration Keys

Common configuration keys include:

| Key | Description | Default |
|-----|-------------|---------|
| `image-registry` | Default container image registry | - |
| `kube-config` | Path to Kubernetes config file | - |
| `git-ssh` | Use SSH for git operations | False |
| `deploy-to` | Default deployment target (compose/k8s) | `compose` |
| `http-proxy-fqdn` | Default HTTP proxy hostname for k8s | - |
| `debug` | Enable debug mode | False |

## Profiles

Configuration profiles can be selected using the `--profile` global option:

```bash
stack --profile production config set image-registry prod.registry.com
```

## Examples

```bash
# Set the default image registry
stack config set image-registry registry.example.com

# Get a specific configuration value
stack config get image-registry

# Show all configuration
stack config show

# Remove a configuration setting
stack config unset git-ssh

# Use a different profile
stack --profile dev config set deploy-to k8s
```

## Configuration File Location

[Placeholder: Add information about where configuration files are stored]

## See Also

- [stack init](init.md) - Create a stack specification file
- [stack deploy](deploy.md) - Deploy a stack
