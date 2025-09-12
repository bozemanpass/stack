# stack update

Update shiv binary from a distribution URL

## Synopsis

```bash
stack update [OPTIONS]
```

## Description

[Placeholder: Add detailed description of how the update command checks for and installs updates to the stack tool itself]

## Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--check-only` | FLAG | Only check for updates, don't install | False |
| `--distribution-url` | TEXT | The distribution URL to check | From config or GitHub releases |

## Default Distribution URL

Default: `https://github.com/bozemanpass/stack/releases/latest/download/stack`

## Update Process

1. Check current version
2. Query distribution URL for latest version
3. Compare versions
4. Download new version if available
5. Replace current binary
6. Verify installation

## Examples

```bash
# Check for updates and install if available
stack update

# Only check for updates (don't install)
stack update --check-only

# Update from custom distribution
stack update --distribution-url https://myrepo.example.com/stack/latest

# Configure custom distribution URL
stack config set distribution-url https://myrepo.example.com/stack/latest
stack update
```

## Version Information

To check current version:
```bash
stack version
```

## Automatic Updates

[Placeholder: Add information about automatic update checks if implemented]

## See Also

- [stack version](version.md) - Print tool version
- [stack config](config.md) - Manage configuration settings
