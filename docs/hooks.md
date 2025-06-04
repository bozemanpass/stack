# Hooks

The behavior of certain `stack` core commands can be extended on a per-pod basis using hooks.  Specifically, the
`init` and `deploy` commands can be extended.

## Directory Structure and Filenames
The hook functions must be located in a file named `./stack/deploy/commands.py` relative to the pod's `composefile.yml`.

The same file may contain an `init` hook, a deploy `hook`, or both.

For example:
```
example-app
├── src
│   ├── ...
├── example-pod
│   ├── composefile.yml
│   └── stack
│       └── deploy
│           └── commands.py
└── stacks
    └── example
        └── stack.yml
```

## Extending `stack init` - the `init` hook

The `stack init` hook is called just before the `Spec` is written to the output file.  This allows the hook 
to examine, add, remove, or alter any settings before output.

The `init` hook _must_ return a `Spec` object, even if no changes are made.

### Signature

```python
def init(deploy_cmd_ctx: DeployCommandContext, spec: Spec) -> Spec:
    return spec
```

## Extending `stack deploy` - the `create` hook

The `deploy` hook is called as the last step in the `stack deploy` process, meaning that all the steps of creating
the deployment directory, copying files, etc. will have been completed before it is called.  This gives the hook an
opportunity to examine the deployment directory and its contents to determine if it needs to generate data,
change configuration, etc.

If `stack deploy` is executed with more than one `--spec-file` option, the `deploy` hook will be called once for
each stack, with the relevant `Stack` object passed to the hook function.

### Signature
```python
# class DeploymentContext:
#     deployment_dir: Path
#     id: str
#     spec: Spec
# ...
 
def create(deploy_cmd_ctx: DeployCommandContext, deployment_ctx: DeploymentContext, stack: Stack) -> None:
    return
```


## Example Code

The built-in `test` stack contains hooks that can serve as a basic example: [commands.py](../src/stack/data/stacks/test/deploy/commands.py).