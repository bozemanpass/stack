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
❯ stack -h
Usage: stack [OPTIONS] COMMAND [ARGS]...

  BPI stack

Options:
  --log-file TEXT  Divert log output to a file (default: stderr; results stay on stdout)
  --debug          enable debug options
  --profile TEXT   name of the configuration profile to use
  --verbose        Log extra details
  --quiet          Suppress unnecessary log output
  -h, --help       Show this message and exit.

Core Commands:
  build     build container images
  config    manage configuration settings for the stack command
  deploy    deploy a stack
  fetch     clone repositories
  init      create a stack specification file
  list      list available stacks
  manage    manage a deployed stack (start, stop, etc.)
  prepare   build or download stack containers
  update    update shiv binary from a distribution url
  validate  check the stack's files for referential integrity
  version   print tool version
  webapp    build, run, and deploy webapps

Example Commands:
  example-hello  hello description here
  example-world  world description here
```

The subcommand is then run by that name, with no option naming the stack it came
from:

```
❯ stack example-hello
Hello
```

## How the Subcommands are Found

There is no `--stack` argument to point at the stack: the command name carries
the stack's name, so `stack` finds the subcommands by searching for stacks the
same way `stack list` does -- beneath the repo base dir, which is where
`stack fetch` puts a stack's repository (`stack config set repo-base-dir` or
`STACK_REPO_BASE_DIR` changes where that is).  A stack outside that directory
contributes no subcommands.  Use `stack list` to check that a stack is where the
search will find it.

The search happens only when a command name is not one of the built-in ones, or
when the help above is formatted, so ordinary commands pay nothing for it.

A subcommand file that fails to import costs its stack its subcommands and
prints a warning; it does not prevent the rest of the CLI from running.

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