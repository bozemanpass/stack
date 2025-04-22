#!/bin/bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

if [ -n "$BPI_SCRIPT_DEBUG" ]; then
    set -x
fi

BPI_BUILD_TOOL="${BPI_BUILD_TOOL}"
BPI_BUILD_OUTPUT_DIR="${BPI_BUILD_OUTPUT_DIR}"

WORK_DIR="${1:-/app}"
DEST_DIR="${2:-/data}"

if [ -f "${WORK_DIR}/webapp build.sh" ]; then
  echo "Building webapp with ${WORK_DIR}/webapp build.sh ..."
  cd "${WORK_DIR}" || exit 1

  rm -rf "${DEST_DIR}"
  ./webapp build.sh "${DEST_DIR}" || exit 1
elif [ -f "${WORK_DIR}/package.json" ]; then
  echo "Building node-based webapp ..."
  cd "${WORK_DIR}" || exit 1

  if [ -z "$BPI_BUILD_TOOL" ]; then
    if [ -f "pnpm-lock.yaml" ]; then
      BPI_BUILD_TOOL=pnpm
    elif [ -f "yarn.lock" ]; then
      BPI_BUILD_TOOL=yarn
    elif [ -f "bun.lockb" ]; then
      BPI_BUILD_TOOL=bun
    else
      BPI_BUILD_TOOL=npm
    fi
  fi

  time $BPI_BUILD_TOOL install || exit 1
  time $BPI_BUILD_TOOL build || exit 1

  rm -rf "${DEST_DIR}"
  if [ -z "${BPI_BUILD_OUTPUT_DIR}" ]; then
    if [ -d "${WORK_DIR}/dist" ]; then
      BPI_BUILD_OUTPUT_DIR="${WORK_DIR}/dist"
    elif [ -d "${WORK_DIR}/build" ]; then
      BPI_BUILD_OUTPUT_DIR="${WORK_DIR}/build"
    else
      echo "ERROR: Unable to locate build output.  Set with --extra-build-args \"--build-arg BPI_BUILD_OUTPUT_DIR=path\"" 1>&2
      exit 1
    fi
  fi
  mv "${BPI_BUILD_OUTPUT_DIR}" "${DEST_DIR}"
else
  echo "Copying static app ..."
  mv "${WORK_DIR}" "${DEST_DIR}"
fi

# One special fix ...
cd "${DEST_DIR}"
for f in $(find . -type f -name '*.htm*'); do
  sed -i -e 's#/BPI_HOSTED_CONFIG_homepage/#BPI_HOSTED_CONFIG_homepage/#g' "$f"
done

exit 0
