# Stack-specific Subcommands

A stack can add its own subcommands to the `stack` command line.  To do so, it simply needs
to have a `subcommands` directory alongside the `stack.yml` with appropriate command files.

## Subcommand Directory Structure and File Location

Each subcommand must be in a distinct file beneath the `subcommands` directory.
The resulting subcommand name will be `<stack_name>-<filename>`.

Example layout:
```
example-app
├── src
│   ├── ...
└── stacks
    └── example
        ├── stack.yml
        └── subcommands
            ├── hello.py
            └── world.py
```

The above adds two subcommands, `example-hello` and `example-world`,
as indicated below in the dynamically added `Example Commands` section
of the help output.

```
❯ stack --stack ~/bpi/example-app/stacks/example -h
Usage: stack [OPTIONS] COMMAND [ARGS]...

  BPI stack

Options:
  --verbose     more detailed output
  --debug       enable debug logging
  --stack TEXT  path to the stack
  -h, --help    Show this message and exit.

Core Commands:
  build    build stack components (containers, etc.)
  config   make configuration files for deploying a stack
  deploy   deploy a stack
  fetch    clone stacks and their required repositories
  manage   manage a deployed stack (start, stop, etc.)
  update   update shiv binary from a distribution url
  version  print tool version
  webapp   build, run, and deploy webapps

Example Commands:
  example-hello  hello description here
  example-world  world description here
```

## Subcommand Code

The subcommand code needs to conform to a few requirements:

1. It needs to be annotated as a `@click.command()`
2. The function needs to be named `command`
3. Technically optional, but strongly recommended, is that it should use `@click.pass_context`
for access to the overall `stack` CLI context.

Example code:
```python
import click

@click.command()
@click.pass_context
def command(ctx):
    """hello description here"""

    print("Hello")
```