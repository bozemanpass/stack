# Contributing

Thank you for taking the time to make a contribution to BPI stack.

## Install (developer mode)

Suitable for developers either modifying or debugging the orchestrator Python code:

### Prerequisites

In addition to the pre-requisites listed in the [README](/README.md), the following are required:

1. Python venv package
   This may or may not be already installed depending on the host OS and version. Check by running:
   ```
   $ python3 -m venv
   usage: venv [-h] [--system-site-packages] [--symlinks | --copies] [--clear] [--upgrade] [--without-pip] [--prompt PROMPT] ENV_DIR [ENV_DIR ...]
   venv: error: the following arguments are required: ENV_DIR
   ```
   If the venv package is missing you should see a message indicating how to install it, for example with:
   ```
   $ apt install python3.10-venv
   ```

### Install

1. Clone this repository:
   ```
   $ git clone https://github.com/bozemanpass/stack.git
   ```

   2. Enter the project directory:
   ```
   $ cd stack
   ```

   3. Setup the virtualenv:
   ```
   $ source ./scripts/developer-mode-setup.sh
   ```

   4. Verify installation:
   ```
   $ (venv)  stack
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

Use shiv to build a single file Python executable zip archive of stack:

1. Run shiv to create a zipapp file:
   ```
   $ (venv)  ./scripts/build_shiv_package.sh
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
