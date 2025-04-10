### Building and Running Webapps

It is possible to build and run Next.js webapps using the `build-webapp` and `run-webapp` subcommands.

To make it easier to build once and deploy into different environments and with different configuration,
compilation and static page generation are separated in the `build-webapp` and `run-webapp` steps.

This offers much more flexibilty than standard Next.js build methods, since any environment variables accessed
via `process.env`, whether for pages or for API, will have values drawn from their runtime deployment environment,
not their build environment. 

## Building

Building usually requires no additional configuration.  By default, the Next.js version specified in `package.json`
is used, and either `yarn` or `npm` will be used automatically depending on which lock files are present.  These
can be overidden with the build arguments `BPI_NEXT_VERSION` and `BPI_BUILD_TOOL` respectively.  For example: `--extra-build-args "--build-arg BPI_NEXT_VERSION=13.4.12"`

**Example**:
```
$ cd ~/bpi
$ git clone git@git.vdb.to:cerc-io/test-progressive-web-app.git
$ stack build-webapp --source-repo ~/bpi/test-progressive-web-app
...

Built host container for ~/bpi/test-progressive-web-app with tag:

    bpi/test-progressive-web-app:stack

To test locally run:

    stack run-webapp --image bpi/test-progressive-web-app:stack --env-file /path/to/environment.env

```

## Running

With `run-webapp` a new container will be launched on the local machine, with runtime configuration provided by `--env-file` (if specified) and published on an available port.  Multiple instances can be launched with different configuration.

**Example**:
```
# Production env
$ stack run-webapp --image bpi/test-progressive-web-app:stack --env-file /path/to/environment/production.env

Image: bpi/test-progressive-web-app:stack
ID: 4c6e893bf436b3e91a2b92ce37e30e499685131705700bd92a90d2eb14eefd05
URL: http://localhost:32768

# Dev env
$ stack run-webapp --image bpi/test-progressive-web-app:stack --env-file /path/to/environment/dev.env

Image: bpi/test-progressive-web-app:stack
ID: 9ab96494f563aafb6c057d88df58f9eca81b90f8721a4e068493a289a976051c
URL: http://localhost:32769
```

## Deploying

Use the subcommand `deploy-webapp create` to make a deployment directory that can be subsequently deployed to a Kubernetes cluster.
Example commands are shown below, assuming that the webapp container image `bpi/test-progressive-web-app:stack` has already been built:
```
$ stack deploy-webapp create --kube-config ~/kubectl/k8s-kubeconfig.yaml --image-registry registry.digitalocean.com/laconic-registry --deployment-dir webapp-k8s-deployment --image bpi/test-progressive-web-app:stack --url https://test-pwa-app.hosting.laconic.com/ --env-file test-webapp.env
$ stack deployment --dir webapp-k8s-deployment push-images
$ stack deployment --dir webapp-k8s-deployment start
```
