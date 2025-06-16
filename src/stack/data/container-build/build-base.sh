# source'ed into container build scripts to do generic command setup
if [[ -n "$STACK_SCRIPT_DEBUG" ]]; then
    set -x
    echo "Build environment variables:"
    env
fi
build_command_args=""
if [[ ${STACK_FORCE_REBUILD} == "true" ]]; then
    build_command_args="${build_command_args} --no-cache"
fi
if [[ -n "$STACK_CONTAINER_EXTRA_BUILD_ARGS" ]]; then
    build_command_args="${build_command_args} ${STACK_CONTAINER_EXTRA_BUILD_ARGS}"
fi
