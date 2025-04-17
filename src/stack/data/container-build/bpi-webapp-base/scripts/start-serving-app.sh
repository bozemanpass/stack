#!/usr/bin/env bash
if [ -n "$BPI_SCRIPT_DEBUG" ]; then
    set -x
fi

BPI_LISTEN_PORT=${BPI_LISTEN_PORT:-80}
BPI_WEBAPP_FILES_DIR="${BPI_WEBAPP_FILES_DIR:-/data}"
BPI_ENABLE_CORS="${BPI_ENABLE_CORS:-false}"
BPI_SINGLE_PAGE_APP="${BPI_SINGLE_PAGE_APP}"

if [ -z "${BPI_SINGLE_PAGE_APP}" ]; then
  # If there is only one HTML file, assume an SPA.
  if [ 1 -eq $(find "${BPI_WEBAPP_FILES_DIR}" -name '*.html' | wc -l) ]; then
    BPI_SINGLE_PAGE_APP=true
  else
    BPI_SINGLE_PAGE_APP=false
  fi
fi

# ${var,,} is a lower-case comparison
if [ "true" == "${BPI_ENABLE_CORS,,}" ]; then
  BPI_HTTP_EXTRA_ARGS="$BPI_HTTP_EXTRA_ARGS --cors"
fi

# ${var,,} is a lower-case comparison
if [ "true" == "${BPI_SINGLE_PAGE_APP,,}" ]; then
  echo "Serving content as single-page app.  If this is wrong, set 'BPI_SINGLE_PAGE_APP=false'"
  # Create a catchall redirect back to /
  BPI_HTTP_EXTRA_ARGS="$BPI_HTTP_EXTRA_ARGS --proxy http://localhost:${BPI_LISTEN_PORT}?"
else
  echo "Serving content normally.  If this is a single-page app, set 'BPI_SINGLE_PAGE_APP=true'"
fi

BPI_HOSTED_CONFIG_FILE=${BPI_HOSTED_CONFIG_FILE}
if [ -z "${BPI_HOSTED_CONFIG_FILE}" ]; then
  if [ -f "/config/bpi-hosted-config.yml" ]; then
    BPI_HOSTED_CONFIG_FILE="/config/bpi-hosted-config.yml"
  elif [ -f "/config/config.yml" ]; then
    BPI_HOSTED_CONFIG_FILE="/config/config.yml"
  fi
fi

if [ -f "${BPI_HOSTED_CONFIG_FILE}" ]; then
  /scripts/apply-webapp-config.sh $BPI_HOSTED_CONFIG_FILE "${BPI_WEBAPP_FILES_DIR}"
fi

/scripts/apply-runtime-env.sh ${BPI_WEBAPP_FILES_DIR}
http-server $BPI_HTTP_EXTRA_ARGS -p ${BPI_LISTEN_PORT} "${BPI_WEBAPP_FILES_DIR}"
