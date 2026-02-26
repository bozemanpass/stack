#!/usr/bin/env bash
if [[ -n "$STACK_SCRIPT_DEBUG" ]]; then
    set -x
fi
uv sync
