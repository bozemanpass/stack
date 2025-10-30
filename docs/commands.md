# Stack Commands

Overview for all stack commands and subcommands. Please see the individual reference pages for documentation on each command, linked below.

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

