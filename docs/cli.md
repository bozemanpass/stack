# bpi-so

Sub-commands and flags

## setup-repositories

Clone a single repository:
```
$ bpi-so setup-repositories --include github.com/cerc-io/go-ethereum
```
Clone the repositories for a stack:
```
$ bpi-so --stack fixturenet-eth setup-repositories
```
Pull latest commits from origin:
```
$ bpi-so --stack fixturenet-eth setup-repositories --pull
```
Use SSH rather than https:
```
$ bpi-so --stack fixturenet-eth setup-repositories --git-ssh
```

## build-containers

Build a single container:
```
$ bpi-so build-containers --include <container-name>
```
e.g.
```
$ bpi-so build-containers --include bpi/go-ethereum
```
Build the containers for a stack:
```
$ bpi-so --stack <stack-name> build-containers
```
e.g.
```
$ bpi-so --stack fixturenet-eth build-containers
```
Force full rebuild of container images:
```
$ bpi-so build-containers --include <container-name> --force-rebuild
```
## build-npms

Build a single package:
```
$ bpi-so build-npms --include <package-name>
```
e.g.
```
$ bpi-so build-npms --include registry-sdk
```
Build the packages for a stack:
```
$ bpi-so --stack <stack-name> build-npms
```
e.g.
```
$ bpi-so --stack fixturenet-laconicd build-npms
```
Force full rebuild of packages:
```
$ bpi-so build-npms --include <package-name> --force-rebuild
```
