#!/bin/bash

if [ -n "$STACK_SCRIPT_DEBUG" ]; then
    set -x
fi

WORK_DIR="${1:-./}"
SRC_DIR="${2:-.next}"
TRG_DIR="${3:-.next-r}"

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

cd "${WORK_DIR}" || exit 1

rm -rf "$TRG_DIR"
mkdir -p "$TRG_DIR"
cp -rp "$SRC_DIR" "$TRG_DIR/"

if [ -f ".env" ]; then
  TMP_ENV=`mktemp`
  declare -px > $TMP_ENV
  set -a
  source .env
  source $TMP_ENV
  set +a
  rm -f $TMP_ENV
fi

for f in $(find . -type f \( -regex '.*.html?' -or -regex ".*.[tj]s\(x\|on\)?$" \) | grep -v 'node_modules' | grep -v '.git'); do
  for e in $(cat "${f}" | tr -s '[:blank:]' '\n' | tr -s '["/\\{},();]' '\n' | tr -s "[']" '\n' | egrep -o -e '^STACK_RUNTIME_ENV_.+$' -e '^STACK_HOSTED_CONFIG_.+$'); do
    orig_name=$(echo -n "${e}" | sed 's/"//g')
    cur_name=$(echo -n "${orig_name}" | sed 's/STACK_RUNTIME_ENV_//g')
    cur_val=$(echo -n "\$${cur_name}" | envsubst)
    if [ "$STACK_RETAIN_ENV_QUOTES" != "true" ]; then
      cur_val=$(sed "s/^[\"']//" <<< "$cur_val" | sed "s/[\"']//")
    fi
    esc_val=$(sed 's/[&/\]/\\&/g' <<< "$cur_val")
    echo "$f: $cur_name=$cur_val"
    sed -i "s/$orig_name/$esc_val/g" $f
  done
done
