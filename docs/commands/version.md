# stack version

Print tool version

## Synopsis

```bash
stack version
```

## Description

[Placeholder: Add detailed description of version command output and version numbering scheme]

## Output Format

The version command outputs:
- Version number (e.g., `2.0.1`)
- Build hash (if available)
- Build timestamp (if available)

Example output:
```
stack version 2.0.1-d531f73-202505011750
```

## Version Components

- **Major version**: Breaking changes
- **Minor version**: New features
- **Patch version**: Bug fixes
- **Build hash**: Git commit hash
- **Timestamp**: Build date and time

## Examples

```bash
# Display version
stack version

# Check version in scripts
if stack version | grep -q "2.0"; then
  echo "Version 2.0 or higher"
fi
```

## See Also

- [stack update](update.md) - Update shiv binary from a distribution URL
