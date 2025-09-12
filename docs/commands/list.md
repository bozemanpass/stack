# stack list

List available stacks

## Synopsis

```bash
stack list [FILTER] [OPTIONS]
```

## Description

[Placeholder: Add detailed description of how list discovers and displays available stacks]

## Arguments

- `FILTER` (optional): Filter pattern to match stack names

## Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--show-path` | FLAG | Show stack path along with name | False |

## Stack Discovery

Stacks are discovered from:
1. Built-in stacks in the stack tool
2. Cloned repositories in `$STACK_REPO_BASE_DIR`
3. Custom stack paths specified with `--stack`

## Output Format

Default output:
```
stack-name-1
stack-name-2
stack-name-3
```

With `--show-path`:
```
stack-name-1: /path/to/stack1
stack-name-2: /path/to/stack2
stack-name-3: /path/to/stack3
```

## Examples

```bash
# List all available stacks
stack list

# List stacks with paths
stack list --show-path

# Filter stacks by pattern
stack list webapp

# Filter with wildcard pattern
stack list "test-*"

# Show paths for filtered stacks
stack list database --show-path
```

## See Also

- [stack check](check.md) - Check if stack containers are ready
- [stack chart](chart.md) - Generate a mermaid graph of the stack
- [stack init](init.md) - Create a stack specification file
