# stack validate

Check the stack's files for referential integrity

## Synopsis

```bash
stack validate [OPTIONS]
```

## Description

Checks that the stack's defining files agree with each other: every locally built
image a pod file uses (`image: <name>:stack`) must be declared as a container in
`stack.yml`, every declared container should be used by some pod file, image
references must be fully specified (no variable interpolation, external images
tagged), and the deprecated `repos:` list and per-pod `repository:` field are
flagged.  The model behind the checks — which file is authoritative for what — is
described in [stack-integrity.md](../stack-integrity.md), along with the full list
of error and warning codes.

A super stack is validated by validating each of its required stacks in isolation
(they must already be fetched).

The same checks run automatically as warnings during
[`stack prepare`](prepare.md), [`stack build`](build.md) and
[`stack init`](init.md); only `stack validate` itself fails on what it finds, which
makes it the form to run in a stack repo's CI.

## Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--stack` | TEXT | Name or path of the stack | - |
| `--strict` | FLAG | Treat warnings as errors | False |

## Exit Codes

- `0`: No errors (warnings may have been reported)
- `1`: One or more errors, or any warning with `--strict`
- `2`: Error occurred during validation

## Examples

```bash
# Validate a stack by name
stack validate --stack my-stack

# Validate the stack in the current directory, failing on warnings too (CI)
stack validate --stack . --strict
```

## See Also

- [stack-integrity.md](../stack-integrity.md) - The model and the full finding list
- [stack check](check.md) - Report what prepare would still have to fetch or build
- [stack prepare](prepare.md) - Build or download the stack's containers
