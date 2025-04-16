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

      5. Verify installation:
         ```
         (venv) $ stack
         Usage: stack [OPTIONS] COMMAND [ARGS]...
         
            BPI stack      
                  
            Options:      
            --stack TEXT               path to the stack to build/deploy
            --quiet      
            --verbose      
            --dry-run      
            --debug      
            --continue-on-e   rror   
            -h, --help                 Show this message and exit.
                  
            Core Commands:      
               build-npms             build the set of npm packages required for a...
               build-webapp           build the specified webapp container
               deploy                 deploy a stack
               deploy-webapp          manage a webapp deployment
               deployment             manage a deployment
               fetch-stack            optionally resolve then git clone a repository...
               prepare-containers     build or download the set of containers required...
               run-webapp             run the specified webapp container
               setup-repositories     git clone the set of repositories required to build...
               update                 update shiv binary from a distribution url
               version                print tool version
            ```   
         
## Build a zipapp (single file distributable script)

Use shiv to build a single file Python executable zip archive of stack:

2. Run shiv to create a zipapp file:
   ```
   $ (venv)  ./scripts/build_shiv_package.sh
   ```
   This creates a file `./stack` that is executable outside of any venv, and on other machines and OSes and architectures, and requiring only the system Python3:

3. Verify it works:
   ```
   $ cp  ~/bin
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
      prepare-containers    build the set of containers required for a complete...
      build-npms          build the set of npm packages required for a...
      deploy              deploy a stack
      setup-repositories  git clone the set of repositories required to build...
      version             print tool version
   ```

For cutting releases, use the [shiv build script](/scripts/build_shiv_package.sh).
