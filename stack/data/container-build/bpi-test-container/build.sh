#!/usr/bin/env bash
# Build bpi/test-container
source ${BPI_CONTAINER_BASE_DIR}/build-base.sh
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
docker build -t bpi/test-container:local -f ${SCRIPT_DIR}/Dockerfile ${build_command_args} $SCRIPT_DIR
