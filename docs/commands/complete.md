# stack complete

Output shell completion script (Hidden Command)

## Synopsis

```bash
stack complete [OPTIONS]
```

## Description

[Placeholder: Add detailed description of shell completion functionality and how to enable it]

This is a hidden command used to generate shell completion scripts for the stack tool.

## Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--shell` | TEXT | Name of shell to generate completions for | `bash` |

## Supported Shells

- `bash` - Bash shell completion
- `zsh` - Z shell completion
- `fish` - Fish shell completion
- [Placeholder: Add other supported shells]

## Installation

### Bash

```bash
# Add to ~/.bashrc
eval "$(stack complete --shell bash)"

# Or save to completion directory
stack complete --shell bash > /etc/bash_completion.d/stack
```

### Zsh

```bash
# Add to ~/.zshrc
eval "$(stack complete --shell zsh)"

# Or save to completion directory
stack complete --shell zsh > ~/.zsh/completions/_stack
```

### Fish

```bash
# Save to fish completion directory
stack complete --shell fish > ~/.config/fish/completions/stack.fish
```

## Features

- Command name completion
- Subcommand completion
- Option name completion
- File path completion for relevant options
- Stack name completion

## Examples

```bash
# Generate bash completion
stack complete --shell bash

# Generate zsh completion
stack complete --shell zsh

# Test completion (bash)
stack <TAB><TAB>

# Complete stack names
stack init --stack <TAB><TAB>

# Complete file paths
stack deploy --spec-file <TAB><TAB>
```

## Troubleshooting

[Placeholder: Add common completion issues and solutions]

## See Also

- Shell documentation for completion systems
- [stack config](config.md) - Manage configuration settings
