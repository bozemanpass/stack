# stack

Sub-commands and flags

## fetch repositories

Clone a single repository:
```
$ stack fetch repositories --include github.com/cerc-io/go-ethereum
```
Clone the repositories for a stack:
```
$ stack --stack fixturenet-eth fetch repositories
```
Pull latest commits from origin:
```
$ stack --stack fixturenet-eth fetch repositories --pull
```
Use SSH rather than https:
```
$ stack --stack fixturenet-eth fetch repositories --git-ssh
```

## prepare-containers

Build a single container:
```
$ stack prepare-containers --include <container-name>
```
e.g.
```
$ stack prepare-containers --include bpi/go-ethereum
```
Build the containers for a stack:
```
$ stack --stack <stack-name> prepare-containers
```
e.g.
```
$ stack --stack fixturenet-eth prepare-containers
```
Force full rebuild of container images:
```
$ stack prepare-containers --include <container-name> --force-rebuild
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
