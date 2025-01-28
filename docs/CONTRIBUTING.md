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

3. (This and the next step can be done by running `source ./scripts/developer-mode-setup.sh`)

   Create and activate a venv:
   ```
   $ python3 -m venv venv
   $ source ./venv/bin/activate
   (venv) $
   ```

4. Install the cli in edit mode:
   ```
   $ pip install --editable .
   ```

   5. Verify installation:
      ```
      (venv) $ stack
      Usage: stack [OPTIONS] COMMAND [ARGS]...

       BPI stack

      Options:
       --quiet
       --verbose
       --dry-run
       -h, --help  Show this message and exit.

      Commands:
       build-containers    build the set of containers required for a complete...
       deploy              deploy a stack
       setup-repositories  git clone the set of repositories required to build...
      ```

## Build a zipapp (single file distributable script)

Use shiv to build a single file Python executable zip archive of stack:

1. Install [shiv](https://github.com/linkedin/shiv):
   ```
   $ (venv) pip install shiv
   $ (venv) pip install wheel
   ```

2. Run shiv to create a zipapp file:
   ```
   $ (venv)  shiv -c stack -o stack .
   ```
   This creates a file `./stack` that is executable outside of any venv, and on other machines and OSes and architectures, and requiring only the system Python3:

3. Verify it works:
   ```
   $ cp stack-orchetrator/stack ~/bin
   $ stack
      Usage: stack [OPTIONS] COMMAND [ARGS]...

      BPI stack

   Options:
      --stack TEXT         specify a stack to build/deploy
      --quiet
      --verbose
      --dry-run
      --local-stack
      --debug
      --continue-on-error
      -h, --help           Show this message and exit.

   Commands:
      build-containers    build the set of containers required for a complete...
      build-npms          build the set of npm packages required for a...
      deploy              deploy a stack
      setup-repositories  git clone the set of repositories required to build...
      version             print tool version
   ```

For cutting releases, use the [shiv build script](/scripts/build_shiv_package.sh).
