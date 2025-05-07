# Hooks

The behavior of certain `stack` core commands can be extended on a per-pod basis using hooks.  Specifically, the
`config init` and `deploy` commands can be extended.

## Directory Structure and Filenames

## Extending `config init`

The `stack config init` hook is called just before the `Spec` is written to the output file.
This allows the hooks to examine, add, remove, or alter any settings before output.

The `init` hook _must_ return a `Spec` object, even if no changes are made.

### Signature

```python
def init(deploy_cmd_ctx: DeployCommandContext, spec: Spec) -> Spec:
    return spec
```

## Extending `deploy`

The `deploy` hook is called as the last step in the `stack deploy` process, meaning that all the steps of creating
the deployment directory, copying files, etc. will have been completed.  This gives the hook an opportunity to examine
the deployment to determine if it needs to generate data, change configuration, etc.

If `stack deploy` is executed with more than one `--spec-file` option, the `deploy` hook will be called
once for each stack, with the active `Stack` object passed to the hook function.

### Signature
```
# class DeploymentContext:
#     deployment_dir: Path
#     id: str
#     spec: Spec
# ...
 
def deploy(deploy_cmd_ctx: DeployCommandContext, deployment_ctx: DeploymentContext, stack: Stack) -> None:
    return
```
