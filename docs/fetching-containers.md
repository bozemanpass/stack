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
* `fetch-repos`   -   Don't build anything, just clone repos.

When building, the resulting containers can be published to the image registry with `--publish-images`.  They will be
published remotely with the form `<image-name>:<git_hash_of_recipe_repo>` such as `bozemanpass/gitea:ae0af8ea5b2de99a49add2b7f7b76dde62a8a617`,
where the *recipe repo* is the repository hosting the container's build declaration (see
[stack-files.md](./stack-files.md#image-identity-and-lock-files)) — for the common case of a repo that carries its own
stack or container files, simply that repo.  The same computation is used when checking for prebuilt images, so knowing
a repository and branch tells you where the corresponding image is and which tag to pull, and an image tag leads back to
the commit (and, via its committed lock files, to every source commit) that produced it.  Images built from uncommitted
or unpinned inputs get a `stackdev-` tag and are never published.

## How discovery works

For each container, under a policy that allows prebuilt images, `stack prepare` proceeds in order:

1. Compute the expected image version: the recipe repo's commit hash (or a `stackdev-` version when the
   checkout is dirty or an input is unpinned — see
   [stack-files.md](./stack-files.md#image-identity-and-lock-files)).
2. If `<image-name>:<version>` exists locally, use it: it is re-tagged as `<image-name>:stack`, which is
   the name deployments consume.
3. Otherwise check the registries (below) for it — skipped entirely for `stackdev-` versions, which are
   never published.  On a hit the image is pulled and re-tagged as `<image-name>:stack`; how the image was
   originally built (wrapper or otherwise) is irrelevant, and none of the build machinery is engaged.
4. Otherwise build locally.

The image name must start with the registry namespace — the GitHub organization for ghcr, the workspace
for Bitbucket — e.g. an image named `myorg/my-app` is looked for at `ghcr.io/myorg/my-app:<version>`.

## Registry auto-detection

The registries checked in step 3 are, in order: the registry given with `--image-registry` (if any), then
a registry inferred from the container's recipe repo — `ghcr.io` for repos on `github.com`, `crg.apkg.io`
for repos on `bitbucket.org`, `registry.gitlab.com` for repos on `gitlab.com`, otherwise the repo host
itself (correct for e.g. self-hosted Gitea).  So for github-hosted containers, prebuilt images are
discovered at `ghcr.io/<image-name>:<recipe-repo-hash>` with no configuration at all, and correspondingly
for the other known hosts.

Auto-detection applies only to *pulling*: publishing with `--publish-images` always requires an explicit
`--image-registry`.

Some registries (Bitbucket's included, unlike ghcr) do not support anonymous pulls at all: `docker login`
is required before either discovery or pulling can succeed.  For Bitbucket, log in with your Atlassian
account email and an [API token](https://id.atlassian.com/manage-profile/security/api-tokens) with
repository read scope as the password — the account password itself is never accepted:

```
$ docker login crg.apkg.io -u you@example.com
```

Registries also differ in whether a first push may create the image name: ghcr creates a package
implicitly, but Bitbucket's registry requires the package to be created (and linked to a repository, whose
permissions it inherits) in the Bitbucket UI before the first push, otherwise the push fails with "name
unknown".  For an image named `<workspace>/<name>`, the package to create is `<name>`.

A remote image only counts as available if its manifest includes the local machine's architecture (or the
`--target-arch` architecture, when given).  If no matching architecture is published the image is treated as
unavailable and, under the `as-needed` policy, built locally instead.

## Checking image availability

It is sometimes useful to check if remote images are available without pulling them.  This is especially useful if you
need to check if images are available a deployment which does not match the current machine architecture (eg, running 
stack from an `arm64` laptop but intending to deploy to an `x64` Kubernetes cluster).  The options `--no-pull` and
`--target-arch` are used in combination to perform this check.

> Note: If your image registry requires authentication, you need to authenticate using `docker login` first.

## Usage
```
# Build locally and then publish remotely.
$ stack prepare --stack my-stack --build-policy build-force --publish-images --image-registry registry.digitalocean.com/example

# Download remote images.
$ stack prepare --stack my-stack --build-policy prebuilt-remote --image-registry registry.digitalocean.com/example

# Check if a remote image is available but don't pull it.
$ stack prepare --stack my-stack --build-policy prebuilt-remote --no-pull --target-arch x64 --image-registry registry.digitalocean.com/example
```