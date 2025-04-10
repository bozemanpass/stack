#!/usr/bin/env bash
# Usage: default-build.sh <image-tag> [<repo-relative-path>]
# if <repo-relative-path> is not supplied, the context is the directory where the Dockerfile lives

source ${BPI_CONTAINER_BASE_DIR}/build-base.sh

if [[ $# -ne 2 ]]; then
    echo "Illegal number of parameters" >&2
    exit 1
fi
image_tag=$1
build_dir=$2
docker build -t ${image_tag} ${build_command_args} --build-arg BPI_HOST_UID=${BPI_HOST_UID} --build-arg BPI_HOST_GID=${BPI_HOST_GID} ${build_dir}
