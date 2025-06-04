#!/usr/bin/env bash
# Build bpi/nextjs-base

source ${BPI_CONTAINER_BASE_DIR}/build-base.sh

# See: https://stackoverflow.com/a/246128/1701505
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

BPI_CONTAINER_BUILD_WORK_DIR=${BPI_CONTAINER_BUILD_WORK_DIR:-$SCRIPT_DIR}
BPI_CONTAINER_BUILD_DOCKERFILE=${BPI_CONTAINER_BUILD_DOCKERFILE:-$SCRIPT_DIR/Dockerfile}
BPI_CONTAINER_BUILD_TAG=${BPI_CONTAINER_BUILD_TAG:-bpi/nextjs-base:stack}

docker build -t $BPI_CONTAINER_BUILD_TAG ${build_command_args} -f $BPI_CONTAINER_BUILD_DOCKERFILE $BPI_CONTAINER_BUILD_WORK_DIR
rc=$?

if [ $rc -ne 0 ]; then
  echo "BUILD FAILED" 1>&2
  exit $rc
fi

if [ "$BPI_CONTAINER_BUILD_TAG" != "bpi/nextjs-base:stack" ]; then
  cat <<EOF

#################################################################

Built host container for $BPI_CONTAINER_BUILD_WORK_DIR with tag:

    $BPI_CONTAINER_BUILD_TAG

To test locally run:

    stack webapp run --image $BPI_CONTAINER_BUILD_TAG --config-file /path/to/environment.env

EOF
fi
