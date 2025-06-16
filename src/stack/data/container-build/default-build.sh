#!/usr/bin/env bash
# Usage: default-build.sh <image-tag> [<repo-relative-path>]
# if <repo-relative-path> is not supplied, the context is the directory where the Containerfile lives

source ${STACK_CONTAINER_BASE_DIR}/build-base.sh

if [[ $# -ne 2 ]]; then
    echo "Illegal number of parameters" >&2
    exit 1
fi
image_tag=$1
build_dir=$2

STACK_CONTAINER_BUILD_CONTAINERFILE=${STACK_CONTAINER_BUILD_CONTAINERFILE}
if [[ -z ${STACK_CONTAINER_BUILD_CONTAINERFILE} ]]; then
    if [[ -f ${build_dir}/Containerfile ]]; then
        STACK_CONTAINER_BUILD_CONTAINERFILE=${build_dir}/Containerfile
    else
        STACK_CONTAINER_BUILD_CONTAINERFILE=${build_dir}/Dockerfile
    fi
fi

docker build -t ${image_tag} \
  --file $STACK_CONTAINER_BUILD_CONTAINERFILE \
  --build-arg STACK_HOST_UID=${STACK_HOST_UID} \
  --build-arg BPI_HOST_GID=${BPI_HOST_GID} \
  ${build_command_args} \
  ${build_dir}
