# Fetching pre-built container images
When BPI stack deploys a stack containing a suite of one or more containers it expects images for those containers to be
on the local machine with a tag of the form `<image-name>:stack` Images for these containers can be built from source
(and optionally base container images from public registries) with the `build containers` subcommand. 

However, the task of building a large number of containers from source may consume considerable time and machine resources.
The default build policy `as-needed` will fetch pre-built containers from an image registry if they are available, and
build images if they are not.

Other build policies include:

* `build`   -   Build the images locally.
* `build-force`   -   Force a clean build of the images locally.
* `prebuilt`   -   Use only prebuilt images, whether they are local or remote.
* `prebuilt-local`   -   Use only prebuilt images available locally.
* `prebuilt-remote`   -   Use only prebuilt images available remotely.

When building, the resulting containers can be published to the image registry with `--publish-images`.  They will be
published remotely with the form `<image-name>:<git_hash_of_container_repo>` such as `bpi/gitea:ae0af8ea5b2de99a49add2b7f7b76dde62a8a617`.

It is sometimes useful to check if remote images are available without pulling them.  This is especially useful if you
need to check if images are available a deployment which does not match the current machine architecture (eg, running 
stack from an `arm64` laptop but intending to deploy to an `x64` Kubernetes cluster).  The options `--no-pull` and
`--target-arch` are used in combination to perform this check.

> Note: If your image registry requires authentication, you need to authenticate using `docker login` first.

## Usage
```
# Build locally and then publish remotely.
$ stack --stack ~/bpi/path/to/my/stack build containers --build-policy build-force --publish-images --image-registry registry.digitalocean.com/example

# Download remote images.
$ stack --stack ~/bpi/path/to/my/stack build containers --build-policy prebuilt-remote --image-registry registry.digitalocean.com/example

# Check if a remote image is available but don't pull it.
$ stack --stack ~/bpi/path/to/my/stack build containers --build-policy prebuilt-remote --no-pull --target-arch x64 --image-registry registry.digitalocean.com/example
```