# Stack Command Reference

Complete reference for all stack commands and subcommands.

## Overview

Stack uses a command/subcommand structure for organizing functionality. Commands are grouped by their primary function.

## Global Options

These options can be used with any command:

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--log-file` | TEXT | Log to file (default stdout/stderr) | - |
| `--debug` | FLAG | Enable debug options | From config |
| `--stack` | TEXT | Name or path of the stack | - |
| `--profile` | TEXT | Configuration profile to use | `config` |
| `--verbose` | FLAG | Log extra details | False |
| `--quiet` | FLAG | Suppress unnecessary log output | False |
| `-h`, `--help` | FLAG | Show help message | - |

## Core Commands

### Repository & Build Management

- [fetch](fetch.md) - Clone repositories and fetch resources
- [prepare](prepare.md) - Build or download stack containers
- [build](build.md) - Build stack components (containers, etc.)

### Stack Configuration

- [init](init.md) - Create a stack specification file
- [config](config.md) - Manage configuration settings

### Deployment & Management

- [deploy](deploy.md) - Deploy a stack
- [manage](manage.md) - Manage a deployed stack (start, stop, etc.)

### Information & Analysis

- [list](list.md) - List available stacks
- [check](check.md) - Check if stack containers are ready
- [chart](chart.md) - Generate a mermaid graph of the stack

### Web Applications

- [webapp](webapp.md) - Build, run, and deploy webapps

### Utility Commands

- [version](version.md) - Print tool version
- [update](update.md) - Update shiv binary from a distribution URL
- [complete](complete.md) - Output shell completion script (hidden)

## Command Groups

Some commands are groups that contain subcommands:

### build
- `containers` - Build stack containers

### config
- `get` - Get configuration value
- `set` - Set configuration value
- `unset` - Remove configuration setting
- `show` - Show full configuration

### fetch
- `repo` - Clone a repository

### manage
- `start` - Start the stack
- `stop` - Stop the stack
- `ps` - List running containers
- `status` - Report stack status
- `logs` - Get container logs
- `exec` - Execute command in container
- `port` - List mapped ports
- `push-images` - Push images to registry
- `reload` - Reload configuration
- `services` - List service names

### webapp
- `build` - Build webapp container
- `deploy` - Deploy webapp
- `run` - Run webapp locally

## Quick Start Examples

### Docker Deployment

```bash
# Fetch a stack
stack fetch repo bozemanpass/example-todo-list

# Prepare containers
stack prepare --stack todo

# Initialize deployment spec
stack init --stack todo --output todo.yml --deploy-to compose

# Deploy the stack
stack deploy --spec-file todo.yml --deployment-dir ~/deployments/todo

# Start the stack
stack manage --dir ~/deployments/todo start

# Check status
stack manage --dir ~/deployments/todo status
```

### Kubernetes Deployment

```bash
# Configure for Kubernetes
stack config set image-registry registry.example.com
stack config set kube-config ~/.kube/config

# Fetch and prepare
stack fetch repo bozemanpass/example-todo-list
stack prepare --stack todo --publish-images

# Initialize for k8s
stack init --stack todo --output todo.yml --deploy-to k8s \
  --http-proxy-fqdn todo.example.com

# Deploy and manage
stack deploy --spec-file todo.yml --deployment-dir ~/deployments/todo-k8s
stack manage --dir ~/deployments/todo-k8s push-images
stack manage --dir ~/deployments/todo-k8s start
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `STACK_CONFIG_PROFILE` | Default configuration profile |
| `STACK_REPO_BASE_DIR` | Base directory for repositories |
| `STACK_DEBUG` | Enable debug mode |
| `STACK_LOG_LEVEL` | Set log level |
| `STACK_USE_BUILTIN_STACK` | Use built-in stack definitions |

## Configuration Files

[Placeholder: Add information about configuration file locations and formats]

## Getting Help

For help with any command:
```bash
stack COMMAND --help
stack COMMAND SUBCOMMAND --help
```

## See Also

- [Installation Guide](../install.md)
- [Contributing Guide](../CONTRIBUTING.md)
- [Recent Features](../recent-features.md)

# Stack Commands Documentation

This documentation provides comprehensive reference for all stack commands and subcommands.

## Command Categories

### 📦 Repository & Build Management
- **[fetch](commands/fetch.md)** - Clone repositories and fetch resources
- **[prepare](commands/prepare.md)** - Build or download stack containers  
- **[build](commands/build.md)** - Build stack components (containers, etc.)

### ⚙️ Stack Configuration
- **[init](commands/init.md)** - Create a stack specification file
- **[config](commands/config.md)** - Manage configuration settings

### 🚀 Deployment & Management
- **[deploy](commands/deploy.md)** - Deploy a stack
- **[manage](commands/manage.md)** - Manage a deployed stack (start, stop, etc.)

### 📊 Information & Analysis
- **[list](commands/list.md)** - List available stacks
- **[check](commands/check.md)** - Check if stack containers are ready
- **[chart](commands/chart.md)** - Generate a mermaid graph of the stack

### 🌐 Web Applications
- **[webapp](commands/webapp.md)** - Build, run, and deploy webapps

### 🔧 Utility Commands
- **[version](commands/version.md)** - Print tool version
- **[update](commands/update.md)** - Update shiv binary from a distribution URL
- **[complete](commands/complete.md)** - Output shell completion script (hidden)

## Quick Reference

| Command | Description |
|---------|-------------|
| `stack build` | Build stack components |
| `stack chart` | Generate visual stack diagram |
| `stack check` | Verify container readiness |
| `stack config` | Manage configuration |
| `stack deploy` | Deploy a stack |
| `stack fetch` | Clone repositories |
| `stack init` | Create stack specification |
| `stack list` | List available stacks |
| `stack manage` | Control deployed stacks |
| `stack prepare` | Prepare containers |
| `stack update` | Update the tool |
| `stack version` | Show version |
| `stack webapp` | Manage web applications |

## Command Groups with Subcommands

### build
- `containers` - Build stack containers

### config  
- `get` - Get configuration value
- `set` - Set configuration value
- `unset` - Remove configuration
- `show` - Display all settings

### fetch
- `repo` - Clone a repository

### manage
- `start` - Start the stack
- `stop` - Stop the stack
- `ps` - List containers
- `status` - Show status
- `logs` - View logs
- `exec` - Execute commands
- `port` - List ports
- `push-images` - Push to registry
- `reload` - Reload config
- `services` - List services

### webapp
- `build` - Build webapp
- `deploy` - Deploy webapp
- `run` - Run locally

## Complete Reference

For a comprehensive overview of all commands with examples and global options, see the **[Command Reference Index](commands/index.md)**.

## Getting Help

To get help for any command, use the `--help` flag:

```bash
# Get help for a main command
stack deploy --help

# Get help for a subcommand
stack manage start --help

# Get general help
stack --help
```

## See Also

- [Installation Guide](install.md)
- [Recent Features](recent-features.md)
- [Contributing Guide](CONTRIBUTING.md)