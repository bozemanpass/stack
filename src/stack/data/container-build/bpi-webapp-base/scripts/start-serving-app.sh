#!/usr/bin/env bash
if [ -n "$STACK_SCRIPT_DEBUG" ]; then
    set -x
fi

STACK_LISTEN_PORT=${STACK_LISTEN_PORT:-80}
STACK_WEBAPP_FILES_DIR="${STACK_WEBAPP_FILES_DIR:-/data}"
STACK_ENABLE_CORS="${STACK_ENABLE_CORS:-false}"
STACK_SINGLE_PAGE_APP="${STACK_SINGLE_PAGE_APP}"

if [ -z "${STACK_SINGLE_PAGE_APP}" ]; then
  # If there is only one HTML file, assume an SPA.
  if [ 1 -eq $(find "${STACK_WEBAPP_FILES_DIR}" -name '*.html' | wc -l) ]; then
    STACK_SINGLE_PAGE_APP=true
  else
    STACK_SINGLE_PAGE_APP=false
  fi
fi

# ${var,,} is a lower-case comparison
if [ "true" == "${STACK_ENABLE_CORS,,}" ]; then
  STACK_HTTP_EXTRA_ARGS="$STACK_HTTP_EXTRA_ARGS --cors"
fi

# ${var,,} is a lower-case comparison
if [ "true" == "${STACK_SINGLE_PAGE_APP,,}" ]; then
  echo "Serving content as single-page app.  If this is wrong, set 'STACK_SINGLE_PAGE_APP=false'"
  # Create a catchall redirect back to /
  STACK_HTTP_EXTRA_ARGS="$STACK_HTTP_EXTRA_ARGS --proxy http://localhost:${STACK_LISTEN_PORT}?"
else
  echo "Serving content normally.  If this is a single-page app, set 'STACK_SINGLE_PAGE_APP=true'"
fi

STACK_HOSTED_CONFIG_FILE=${STACK_HOSTED_CONFIG_FILE}
if [ -z "${STACK_HOSTED_CONFIG_FILE}" ]; then
  if [ -f "/config/bpi-hosted-config.yml" ]; then
    STACK_HOSTED_CONFIG_FILE="/config/bpi-hosted-config.yml"
  elif [ -f "/config/config.yml" ]; then
    STACK_HOSTED_CONFIG_FILE="/config/config.yml"
  fi
fi

if [ -f "${STACK_HOSTED_CONFIG_FILE}" ]; then
  /scripts/apply-webapp-config.sh $STACK_HOSTED_CONFIG_FILE "${STACK_WEBAPP_FILES_DIR}"
fi

/scripts/apply-runtime-env.sh ${STACK_WEBAPP_FILES_DIR}
http-server $STACK_HTTP_EXTRA_ARGS -p ${STACK_LISTEN_PORT} "${STACK_WEBAPP_FILES_DIR}"
