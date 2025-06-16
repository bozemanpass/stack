#!/usr/bin/env bash
# Build bpi/webapp-base

source ${STACK_CONTAINER_BASE_DIR}/build-base.sh

# See: https://stackoverflow.com/a/246128/1701505
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

STACK_CONTAINER_BUILD_WORK_DIR=${STACK_CONTAINER_BUILD_WORK_DIR:-$SCRIPT_DIR}
STACK_CONTAINER_BUILD_CONTAINERFILE=${STACK_CONTAINER_BUILD_CONTAINERFILE:-$SCRIPT_DIR/Containerfile}
STACK_CONTAINER_BUILD_TAG=${STACK_CONTAINER_BUILD_TAG:-bpi/webapp-base:stack}

docker build -t $STACK_CONTAINER_BUILD_TAG ${build_command_args} -f $STACK_CONTAINER_BUILD_CONTAINERFILE $STACK_CONTAINER_BUILD_WORK_DIR
rc=$?

if [ $rc -ne 0 ]; then
  echo "BUILD FAILED" 1>&2
  exit $rc
fi

if [ "$STACK_CONTAINER_BUILD_TAG" != "bpi/webapp-base:stack" ]; then
  cat <<EOF

#################################################################

Built host container for $STACK_CONTAINER_BUILD_WORK_DIR with tag:

    $STACK_CONTAINER_BUILD_TAG

To test locally run:

    stack webapp run --image $STACK_CONTAINER_BUILD_TAG --config-file /path/to/environment.env

EOF
fi
