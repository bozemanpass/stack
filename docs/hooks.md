# Hooks

The behavior of certain `stack` core commands can be extended by a stack, using hooks.  Specifically, the
`init` and `deploy` commands can be extended.

## Directory Structure and Filenames
The hook functions live in a file named `commands.py`, in a `deploy` directory.  Where that
directory sits depends on which of the two `pods:` formats the `stack.yml` uses.

The same file may contain an `init` hook, a `create` hook, or both.

For a stack whose pods are declared with a `name` and a `path`, the hooks belong to the pod,
in `./stack/deploy/commands.py` relative to the pod's `composefile.yml`:

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

For a stack whose pods are declared as plain strings, there is no per-pod directory to hang
them on, so the hooks belong to the stack, alongside its `stack.yml`:

```
example-stacks
├── compose
│   └── composefile-web.yml
└── stacks
    └── example
        ├── stack.yml          # its pods: list is just [web]
        └── deploy
            └── commands.py
```

A stack in either layout gets the same hooks called with the same arguments; only where the
tool looks for them differs.

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

The `test` stack in
[stack-test-stacks](https://github.com/bozemanpass/stack-test-stacks/blob/main/stack-files/stacks/test-stack/deploy/commands.py)
has both hooks, in the second of the two layouts above.  They exist to be observed rather
than to do anything useful — each leaves a side effect that this repo's smoke test asserts
on — so they are a small and complete example of the calling convention.