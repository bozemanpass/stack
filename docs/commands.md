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
- [CLI Overview](cli.md)
- [Recent Features](recent-features.md)
- [Contributing Guide](CONTRIBUTING.md)