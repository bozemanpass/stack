### Building and Running Webapps

It is possible to build and run static, React, and Next.js webapps using the `webapp build` and `webapp run` subcommands.

To make it easier to build once and deploy into different environments and with different configuration,
compilation and static page generation are separated in the `webapp build` and `webapp run` steps.

This offers much more flexibility than standard Next.js build methods, since any environment variables accessed
via `process.env`, whether for pages or for API, will have values drawn from their runtime deployment environment,
not their build environment. 

## Building

Building usually requires no additional configuration.  By default, the Next.js version specified in `package.json`
is used, and either `yarn` or `npm` will be used automatically depending on which lock files are present.  These
can be overidden with the build arguments `STACK_NEXT_VERSION` and `STACK_BUILD_TOOL` respectively.  For example: `--extra-build-args "--build-arg STACK_NEXT_VERSION=13.4.12"`

**Example**:
```
$ cd ~/bpi
$ git clone https://github.com/bozemanpass/test-progressive-web-app
$ stack webapp build --source-repo ~/bpi/test-progressive-web-app
...

Built host container for ~/bpi/test-progressive-web-app with tag:

    bpi/test-progressive-web-app:stack

To test locally run:

    stack webapp run --image bpi/test-progressive-web-app:stack --config-file /path/to/environment.env

```

## Running

With `webapp run` a new container will be launched on the local machine, with runtime configuration provided by `--config-file` (if specified) and published on an available port.  Multiple instances can be launched with different configuration.

**Example**:
```
# Production env
$ stack webapp run --image bpi/test-progressive-web-app:stack --config-file /path/to/environment/production.env

Image: bpi/test-progressive-web-app:stack
ID: 4c6e893bf436b3e91a2b92ce37e30e499685131705700bd92a90d2eb14eefd05
URL: http://localhost:32768

# Dev env
$ stack webapp run --image bpi/test-progressive-web-app:stack --config-file /path/to/environment/dev.env

Image: bpi/test-progressive-web-app:stack
ID: 9ab96494f563aafb6c057d88df58f9eca81b90f8721a4e068493a289a976051c
URL: http://localhost:32769
```

## Deploy and Run

Use the subcommand `webapp deploy` to make a deployment directory that can be subsequently deployed to a Kubernetes cluster.
Example commands are shown below, assuming that the webapp container image `bpi/test-progressive-web-app:stack` has already been built:
```
$ stack webapp deploy --kube-config ~/kubectl/k8s-kubeconfig.yaml --image-registry registry.digitalocean.com/laconic-registry --deployment-dir ~/bpi/webapp-k8s-deployment --image bpi/test-progressive-web-app:stack --url https://test-pwa-app.bpi.servesthe.world --config-file test-webapp.env
$ stack manage --dir ~/bpi/webapp-k8s-deployment push-images
$ stack manage --dir ~/bpi/webapp-k8s-deployment start
```
