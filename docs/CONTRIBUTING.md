# Contributing

Thank you for taking the time to make a contribution to BPI stack.

## Install (developer mode)

Suitable for developers either modifying or debugging the orchestrator Python code:

### Prerequisites

In addition to the pre-requisites listed in the [README](/README.md), the following are required:

1. [uv](https://docs.astral.sh/uv/getting-started/installation/) — used for dependency management and virtual environments.

### Install

1. Clone this repository:
   ```
   $ git clone https://github.com/bozemanpass/stack.git
   ```

2. Enter the project directory:
   ```
   $ cd stack
   ```

3. Install dependencies:
   ```
   $ ./scripts/developer-mode-setup.sh
   ```
   This runs `uv sync`, which creates a `.venv` virtual environment and installs all dependencies.

4. Verify installation:
   ```
   $ uv run stack
      Usage: stack [OPTIONS] COMMAND [ARGS]...

      BPI stack

      Options:
         --verbose       more detailed output
         --debug         enable debug logging
         --stack TEXT    path to the stack
         --profile TEXT  name of the configuration profile to use
         -h, --help      Show this message and exit.

      Core Commands:
         config   manage configuration settings for the stack command
         deploy   deploy a stack
         fetch    clone repositories
         init     create a stack specification file
         list     list available stacks
         manage   manage a deployed stack (start, stop, etc.)
         prepare  prepare a stack by cloning repositories and building and...
         update   update shiv binary from a distribution url
         version  print tool version
         webapp   build, run, and deploy webapps
   ```

## Build a zipapp (single file distributable script)

Use shiv (via `uvx`) to build a single file Python executable zip archive of stack:

1. Run shiv to create a zipapp file:
   ```
   $ ./scripts/build_shiv_package.sh
   ```
   This creates a file under `./package/` that is executable outside of any venv, and on other machines and OSes and architectures, and requiring only the system Python3:

2. Verify it works:
   ```
   # Note: Your binary will have a different hash and timestamp in the name
   $ cp package/stack-2.0.0-d531f73-202505011750 ~/bin
   $ stack
      Usage: stack [OPTIONS] COMMAND [ARGS]...

   ...
   ```
