#!/bin/bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

if [ -n "$STACK_SCRIPT_DEBUG" ]; then
    set -x
fi

STACK_BUILD_TOOL="${STACK_BUILD_TOOL}"
STACK_BUILD_OUTPUT_DIR="${STACK_BUILD_OUTPUT_DIR}"

WORK_DIR="${1:-/app}"
DEST_DIR="${2:-/data}"

if [ -f "${WORK_DIR}/webapp-build.sh" ]; then
  echo "Building webapp with ${WORK_DIR}/webapp-build.sh ..."
  cd "${WORK_DIR}" || exit 1
  eval $(${SCRIPT_DIR}/convert-to-runtime-env.sh .)

  rm -rf "${DEST_DIR}"
  ./webapp-build.sh "${DEST_DIR}" || exit 1
elif [ -f "${WORK_DIR}/package.json" ]; then
  echo "Building package.json based webapp ..."
  cd "${WORK_DIR}" || exit 1
  eval $(${SCRIPT_DIR}/convert-to-runtime-env.sh .)

  STACK_BUILD_TOOL_INSTALL_SUBCOMMAND="${STACK_BUILD_TOOL_INSTALL_SUBCOMMAND:-install}"
  STACK_BUILD_TOOL_BUILD_SUBCOMMAND="${STACK_BUILD_TOOL_BUILD_SUBCOMMAND:-build}"

  if [ -z "$STACK_BUILD_TOOL" ]; then
    if [ -f "pnpm-lock.yaml" ]; then
      STACK_BUILD_TOOL=pnpm
    elif [ -f "yarn.lock" ]; then
      STACK_BUILD_TOOL=yarn
    elif [ -f "bun.lockb" ]; then
      STACK_BUILD_TOOL=bun
    else
      STACK_BUILD_TOOL=npm
      STACK_BUILD_TOOL_BUILD_SUBCOMMAND="run build"
    fi
  fi

  time $STACK_BUILD_TOOL $STACK_BUILD_TOOL_INSTALL_SUBCOMMAND || exit 1
  time $STACK_BUILD_TOOL $STACK_BUILD_TOOL_BUILD_SUBCOMMAND || exit 1

  rm -rf "${DEST_DIR}"
  if [ -z "${STACK_BUILD_OUTPUT_DIR}" ]; then
    if [ -d "${WORK_DIR}/dist" ]; then
      STACK_BUILD_OUTPUT_DIR="${WORK_DIR}/dist"
    elif [ -d "${WORK_DIR}/build" ]; then
      STACK_BUILD_OUTPUT_DIR="${WORK_DIR}/build"
    else
      echo "ERROR: Unable to locate build output.  Set with --extra-build-args \"--build-arg STACK_BUILD_OUTPUT_DIR=path\"" 1>&2
      exit 1
    fi
  fi
  mv "${STACK_BUILD_OUTPUT_DIR}" "${DEST_DIR}"
else
  echo "Copying static app ..."
  mv "${WORK_DIR}" "${DEST_DIR}"
fi

# One special fix ...
cd "${DEST_DIR}"
for f in $(find . -type f -name '*.htm*'); do
  sed -i -e 's#/STACK_HOSTED_CONFIG_homepage/#STACK_HOSTED_CONFIG_homepage/#g' "$f"
done

exit 0
