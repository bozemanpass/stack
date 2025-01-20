# Stack

Stack allows building and deployment of a suite of related applications as a single "stack".  It is a fork of https://git.vdb.to/cerc-io/stack intended for general use.

## Install

**To get started quickly** on a fresh Ubuntu instance (e.g, Digital Ocean); [try this script](./scripts/quick-install-linux.sh). **WARNING:** always review scripts prior to running them so that you know what is happening on your machine.

For any other installation, follow along below and **adapt these instructions based on the specifics of your system.**


Ensure that the following are already installed:

- [Python3](https://wiki.python.org/moin/BeginnersGuide/Download): `python3 --version` >= `3.8.10` (the Python3 shipped in Ubuntu 20+ is good to go)
- [Docker](https://docs.docker.com/get-docker/): `docker --version` >= `20.10.21`
- [jq](https://stedolan.github.io/jq/download/): `jq --version` >= `1.5`
- [git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git): `git --version` >= `2.10.3`

Note: if installing docker-compose via package manager on Linux (as opposed to Docker Desktop), you must [install the plugin](https://docs.docker.com/compose/install/linux/#install-the-plugin-manually), e.g. :

```bash
mkdir -p ~/.docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/download/v2.11.2/docker-compose-linux-x86_64 -o ~/.docker/cli-plugins/docker-compose
chmod +x ~/.docker/cli-plugins/docker-compose
```

Next decide on a directory where you would like to put the stack program. Typically this would be 
a "user" binary directory such as `~/bin` or perhaps `/usr/local/laconic` or possibly just the current working directory.

Now, having selected that directory, download the latest release from [this page](https://github.com/bozemanpass/stack/tags) into it (we're using `~/bin` below for concreteness but edit to suit if you selected a different directory). Also be sure that the destination directory exists and is writable:

```bash
curl -L -o ~/bin/bpi-so https://github.com/bozemanpass/stack/releases/download/latest/bpi-so
```

Give it execute permissions:

```bash
chmod +x ~/bin/bpi-so
```

Ensure `bpi-so` is on the [`PATH`](https://unix.stackexchange.com/a/26059)

Verify operation (your version will probably be different, just check here that you see some version output and not an error):

```
bpi-so version
Version: 1.1.0-7a607c2-202304260513
```
Save the distribution url to `~/.bpi-so/config.yml`:
```bash
mkdir ~/.bpi-so
echo "distribution-url: https://github.com/bozemanpass/stack/releases/download/latest/bpi-so" >  ~/.bpi-so/config.yml
```

### Update
If Stack Orchestrator was installed using the process described above, it is able to subsequently self-update to the current latest version by running:

```bash
bpi-so update
```

## Usage

The various [stacks](/stack/data/stacks) each contain instructions for running different stacks based on your use case. For example:

- [self-hosted Gitea](/stack/data/stacks/build-support)
- [an Optimism Fixturenet](/stack/data/stacks/fixturenet-optimism)
- [laconicd with console and CLI](stack/data/stacks/fixturenet-laconic-loaded)
- [kubo (IPFS)](stack/data/stacks/kubo)

## Contributing

See the [CONTRIBUTING.md](/docs/CONTRIBUTING.md) for developer mode install.

## Platform Support

Native aarm64 is _not_ currently supported. x64 emulation on ARM64 macos should work (not yet tested).



