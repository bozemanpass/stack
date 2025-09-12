# stack chart

Generate a mermaid graph of the stack

## Synopsis

```bash
stack chart [OPTIONS]
```

## Description

[Placeholder: Add detailed description of how the chart command generates visual representations of stack architecture using Mermaid diagrams]

## Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--stack` | TEXT | Name or path of the stack | - |
| `--show-ports/--no-show-ports` | FLAG | Show port mappings in the chart | False |
| `--show-http-targets/--no-show-http-targets` | FLAG | Show HTTP proxy targets in the chart | True |
| `--show-volumes/--no-show-volumes` | FLAG | Show volume mounts in the chart | True |

## Output Format

The command generates a Mermaid diagram that can be rendered using:
- Mermaid CLI tools
- Markdown renderers with Mermaid support
- Online Mermaid editors

## Examples

```bash
# Generate a basic chart for a stack
stack chart --stack my-stack

# Generate a chart showing all details
stack chart --stack my-stack --show-ports

# Generate a minimal chart without volumes
stack chart --stack my-stack --no-show-volumes --no-show-http-targets
```

## See Also

- [stack list](list.md) - List available stacks
- [stack check](check.md) - Check if stack containers are ready
