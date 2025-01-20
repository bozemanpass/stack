# stack

Sub-commands and flags

## setup-repositories

Clone a single repository:
```
$ stack setup-repositories --include github.com/cerc-io/go-ethereum
```
Clone the repositories for a stack:
```
$ stack --stack fixturenet-eth setup-repositories
```
Pull latest commits from origin:
```
$ stack --stack fixturenet-eth setup-repositories --pull
```
Use SSH rather than https:
```
$ stack --stack fixturenet-eth setup-repositories --git-ssh
```

## build-containers

Build a single container:
```
$ stack build-containers --include <container-name>
```
e.g.
```
$ stack build-containers --include bpi/go-ethereum
```
Build the containers for a stack:
```
$ stack --stack <stack-name> build-containers
```
e.g.
```
$ stack --stack fixturenet-eth build-containers
```
Force full rebuild of container images:
```
$ stack build-containers --include <container-name> --force-rebuild
```
## build-npms

Build a single package:
```
$ stack build-npms --include <package-name>
```
e.g.
```
$ stack build-npms --include registry-sdk
```
Build the packages for a stack:
```
$ stack --stack <stack-name> build-npms
```
e.g.
```
$ stack --stack fixturenet-laconicd build-npms
```
Force full rebuild of packages:
```
$ stack build-npms --include <package-name> --force-rebuild
```
