# source'ed into container build scripts to do generic command setup
if [[ -n "$BPI_SCRIPT_DEBUG" ]]; then
    set -x
    echo "Build environment variables:"
    env
fi
build_command_args=""
if [[ ${BPI_FORCE_REBUILD} == "true" ]]; then
    build_command_args="${build_command_args} --no-cache"
fi
if [[ -n "$BPI_CONTAINER_EXTRA_BUILD_ARGS" ]]; then
    build_command_args="${build_command_args} ${BPI_CONTAINER_EXTRA_BUILD_ARGS}"
fi
