# stack

Sub-commands and flags

## fetch repositories

Clone the repositories for a stack:
```
$ stack fetch repositories --stack ~/bpi/gitea-stack
```
Pull latest commits from origin:
```
$ stack fixturenet-eth fetch repositories --stack ~/bpi/gitea-stack --pull
```
Use SSH rather than https:
```
$ stack fixturenet-eth fetch repositories --stack ~/bpi/gitea-stack --git-ssh
```

## build containers

Build a single container:
```
$ stack build containers --include <container-name>
```
e.g.
```
$ stack build containers --include bpi/go-ethereum
```
Build the containers for a stack:
```
$ stack --stack <stack-name> build containers
```
e.g.
```
$ stack --stack fixturenet-eth build containers
```
Force full rebuild of container images:
```
$ stack build containers --include <container-name> --force-rebuild
```