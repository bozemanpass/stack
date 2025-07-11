## stack.yml

The `stack.yml` file defines the structure and configuration of a deployment stack. It specifies the containers, pods,
and any pre/post-start commands required for the deployment.

### Example

```yaml
# The name of the stack.
name: gitea
# A brief description of the stack (optional).
description: "Gitea SCM and Actions"
# A list of containers to be used in the stack.
containers:
    # The name of the container in the form `<organization>/<name>`.  The pod's composefile.yml will need to use the
    # same name for the image with the tag `stack`.  For example: `image: bozemanpass/act-runner:stack`
  - name: bozemanpass/act-runner
    # An (optional) reference to the container's repository.  The format is: [hostname/]organization/repo[@tag_or_branch]
    # The hostname is optional.  When omitted, github.com is assumed.  The tag is also optional.  If omitted,
    # the main repo branch is used.  If `ref` is omitted entirely, the current repo is assumed.
    ref: bozemanpass/gitea-containers
    # The relative path in the repo to the container build info.  This directory must contain one (or more) of:
    #   - container.yml descriptor file (more info below)
    #   - build.sh build script
    #        The result of execution should be a local image tagged `<name>:stack`.  The exact tag is available
    #        in the script build environment under ${STACK_DEFAULT_CONTAINER_IMAGE_TAG}.
    #   - Dockerfile
    #        The container will be built using the Dockerfile in this directory similar to:
    #             docker build -t ${STACK_DEFAULT_CONTAINER_IMAGE_TAG} .
    path: ./act-runner
  - name: bozemanpass/gitea
    ref: bozemanpass/gitea-containers
    path: ./gitea
# Pods are groups of containers that are deployed together.  Each pod corresponds to one composefile.yml.
pods:
    # The name of the pod.
  - name: gitea
    # The relative path in this repo to the directory containing the pod composefile.yml and other files.
    path: ./gitea
    # An (optional) command to run just _before_ the pod starts. The command is executed on the host, and the location
    # is relative to the `path` specified above.  The deployment directory will be set in the environment under
    # ${STACK_DEPLOYMENT_DIR}, allowing a script to execute commands _inside_ the service containers with: 
    #     stack manage --dir ${STACK_DEPLOYMENT_DIR} exec <service> <command>
    pre_start_command: "run-this-first.sh"
    # Similar to pre_start_command, but executed _after_ the pod starts.
    post_start_command: "initialize-gitea.sh"
  - name: act-runner
    path: ./act-runner
    pre_start_command: "pre_start.sh"
    post_start_command: "post_start.sh"
```

## container.yml

The `container.yml` file defines the build configuration for individual containers within a stack.  It specifies the container's name,
the repository reference, and the build script or command to be used for building the container image.

The build script path is relative to the `container.yml` file, not the target repo.  In practice, this allows for build
scripts to be located in a separate repo from the container's source code, which is very useful for building customized
container images from repositories that are not under your control.

The following example from the `bozemanpass/gitea-containers` repo builds the `bozemanpass/act-runner` container directly from
the `gitea.com/gitea/act_runner` repo, for example.

### Example
```yaml
container:
  # The name of the container in the form `<organization>/<name>`.  The pod's composefile.yml will need to use the
  # same name for the image with the tag `stack`.  For example: `image: bozemanpass/act-runner:stack`
  name: bozemanpass/act-runner
  # An optional reference to the container's repository.  The format is: [hostname/]organization/repo[@tag_or_branch]
  # The hostname is optional.  When omitted, github.com is assumed.  The tag is also optional.  If omitted,
  # the main repo branch is used.  If `ref` is omitted entirely, the current repo is assumed.
  ref: gitea.com/gitea/act_runner
  # Optional path to the container build script or command.  This path is relative to the `container.yml` file.
  # If no build script is provided, the default build command will be used.
  build: ./build.sh
```

## container.lock

The `container.lock` file contains the git commit hash of the target repo.  If not already present, the file is
automatically generated when the container is built.  It can be committed to the repo to ensure the build will be
repeatable in the future, and when the repository is pulled by `stack` the appropriate commit will be checked out.

> Note: Even when `container.lock` is present, any local code changes will be included when building the container,
> since the hash is used only when the repository is cloned or pulled.

## composefile.yml

The `composefile.yml` file defines the structure and configuration of a pod. It specifies the containers, volumes, 
environment variables, and any other settings required for the pod's deployment.

It is compatible in syntax with `docker-compose.yml`.

### Example
```yaml
services:
  runner:
    image: bozemanpass/act-runner:stack
    restart: always
    privileged: true
    environment:
      - CONFIG_FILE=/config/act-runner-config.yml
      - GITEA_INSTANCE_URL=http://${STACK_SVC_GITEA}:3000
    volumes:
      - act-runner-data:/data
      - act-runner-config:/config:ro
    ports:
      - 8088

volumes:
  act-runner-data:
  act-runner-config:
```

### Environment Variables for Service Hostnames

When using `stack` to manage a pod, the service hostnames are automatically set in the environment variables for
each service.  This allows for easy access to the hostnames of other services within the same deployment.  The variables
are in the form `$STACK_SVC_<NAME>`, where `<NAME>` is the uppercase name of the service name as it appears in the
`composefile.yml`.  In the example above, `$STACK_SVC_GITEA` would contain the hostname of the `gitea` service (located
in another pod in the same deployment), and `$STACK_SVC_RUNNER` would be set to the hostname of the `runner` service.