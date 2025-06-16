#!/usr/bin/env bash
if [ -n "$STACK_SCRIPT_DEBUG" ]; then
    set -x
fi


SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
STACK_MAX_GENERATE_TIME=${STACK_MAX_GENERATE_TIME:-120}
tpid=""

ctrl_c() {
    kill $tpid $(ps -ef | grep node | grep next | awk '{print $2}') 2>/dev/null
}

trap ctrl_c INT

STACK_BUILD_TOOL="${STACK_BUILD_TOOL}"
if [ -z "$STACK_BUILD_TOOL" ]; then
  if [ -f "pnpm-lock.yaml" ]; then
    STACK_BUILD_TOOL=pnpm
  elif [ -f "yarn.lock" ]; then
    STACK_BUILD_TOOL=yarn
  elif [ -f "bun.lockb" ]; then
    STACK_BUILD_TOOL=bun
  else
    STACK_BUILD_TOOL=npm
  fi
fi

STACK_WEBAPP_FILES_DIR="${STACK_WEBAPP_FILES_DIR:-/app}"
cd "$STACK_WEBAPP_FILES_DIR"

"$SCRIPT_DIR/apply-runtime-env.sh" "`pwd`" .next .next-r
mv .next .next.old
mv .next-r/.next .

if [ "$STACK_NEXTJS_SKIP_GENERATE" != "true" ]; then
  jq -e '.scripts.bpi_generate' package.json >/dev/null
  if [ $? -eq 0 ]; then
    npm run bpi_generate > gen.out 2>&1 &
    tail -f gen.out &
    tpid=$!

    count=0
    generate_done="false"
    while [ $count -lt $STACK_MAX_GENERATE_TIME ] && [ "$generate_done" == "false" ]; do
      sleep 1
      count=$((count + 1))
      grep 'rendered as static' gen.out > /dev/null
      if [ $? -eq 0 ]; then
        generate_done="true"
      fi
    done

    if [ $generate_done != "true" ]; then
      echo "ERROR: 'npm run bpi_generate' not successful within STACK_MAX_GENERATE_TIME" 1>&2
      exit 1
    fi

    kill $tpid $(ps -ef | grep node | grep next | grep generate | awk '{print $2}') 2>/dev/null
    tpid=""
  fi
fi

$STACK_BUILD_TOOL start . -- -p ${STACK_LISTEN_PORT:-80}
