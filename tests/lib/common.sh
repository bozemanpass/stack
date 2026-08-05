#!/usr/bin/env bash
#
# Shared helpers for the integration test scripts -- the bash suites under
# tests/, not the pytest suite in tests/unit.
#
# Source this as the first thing a test script does:
#
#     source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"
#
# Sourcing it turns on `set -e`, applies STACK_SCRIPT_DEBUG (xtrace plus an
# environment dump), and defines the helpers below.  The scripts still expect to
# be run from the repo root, since the package under test is found in ./package.
#
# These scripts grew by copying each other, and every copied helper eventually
# drifted: a fix would land in one copy and not its siblings (the retry limit
# raised for slow image pulls in one wait loop, the response-body dump added to
# one HTTP wait, a `ps` marker that the product stopped printing).  So anything
# needed by more than one test belongs here, and divergence between tests should
# be a parameter rather than a second copy.

set -e

if [ -n "$STACK_SCRIPT_DEBUG" ]; then
  set -x
  echo "Environment variables:"
  env
fi

# The deployment the helpers below act on; set by stop_deployment_on_exit.
TEST_DEPLOYMENT_DIR=""

# Optionally the name of a function run during teardown, for a test that has
# cleanup of its own to do (a scratch registry container, say).
TEST_EXTRA_CLEANUP=""

# --- reporting ---------------------------------------------------------------

# Report a failure and exit non-zero.  Teardown registered with
# stop_deployment_on_exit still runs, so a test never needs to call its own
# cleanup function by hand before failing.
fail () {
    echo "$@"
    exit 1
}

# --- preconditions -----------------------------------------------------------

# Check that the utilities a test needs are on the PATH.
require_commands () {
    local cmd
    for cmd in "$@"; do
        if ! command -v "$cmd" &> /dev/null; then
            fail "Error: '$cmd' is not installed or not available on the PATH"
        fi
    done
}

# --- the package under test --------------------------------------------------

# Pick the stack executable to test, setting TEST_TARGET_STACK, and report it
# along with the version it claims.  Pass the test script's arguments through:
#
#     select_test_target "$@"
#
# In precedence order: an inherited TEST_TARGET_STACK (so a developer can point
# a test at "uv run stack"), then "from-path" as the first argument, then the
# most recently built shiv package in ./package.
select_test_target () {
    if [ -z "$TEST_TARGET_STACK" ]; then
        if [ "$1" == "from-path" ]; then
            TEST_TARGET_STACK="stack"
        else
            TEST_TARGET_STACK=$( ls -t1 ./package/stack* | head -1 )
        fi
    fi
    echo "Testing this package: $TEST_TARGET_STACK"
    echo "Version reported is: $( $TEST_TARGET_STACK version )"
}

# --- test directories --------------------------------------------------------

# Remove a directory even when it holds root-owned files.  Containers write into
# bind-mounted volume dirs as root, so a previous run's data cannot always be
# removed by the (non-root) host user; fall back to a throwaway container.
force_rm () {
    if [ -e "$1" ]; then
        rm -rf "$1" 2> /dev/null || true
    fi
    if [ -e "$1" ]; then
        docker run --rm -v "$( dirname "$1" )":/w alpine rm -rf "/w/$( basename "$1" )"
    fi
}

# Create a clean working directory for the test under ~/stack-test and put the
# stack tool's repo base dir inside it.  Sets STACK_TEST_DIR and exports
# STACK_REPO_BASE_DIR.  Each test passes its own directory name, so tests do not
# share state with each other.
setup_test_dir () {
    STACK_TEST_DIR=~/stack-test/"$1"
    export STACK_REPO_BASE_DIR=${STACK_TEST_DIR}/repo-base-dir
    echo "Using test directory: $STACK_TEST_DIR"
    force_rm "$STACK_TEST_DIR"
    mkdir -p "$STACK_REPO_BASE_DIR"
}

# --- container images --------------------------------------------------------

# Remove every local copy of an image, so that what follows exercises a real
# build or pull instead of silently reusing whatever happened to be present.
# Deliberately fails loudly: if the image survives, the test that follows is not
# testing what it claims to.
remove_local_images () {
    local existing
    existing=$( docker image ls -q --filter=reference="$1" | uniq )
    if [ -n "$existing" ]; then
        docker image rm -f ${existing}
    fi
}

# --- deployment lifecycle ----------------------------------------------------

# Register teardown for a deployment, and tell the wait helpers below which
# deployment they are acting on.  From here on any exit -- success, `fail`, or an
# error under `set -e` -- stops the deployment and deletes its volumes.
#
# On a failing exit the containers' logs are dumped first: the deployment is
# about to be destroyed, and in CI those logs are usually the only evidence of
# what went wrong.
stop_deployment_on_exit () {
    TEST_DEPLOYMENT_DIR="$1"
    trap _test_exit_handler EXIT
}

_test_exit_handler () {
    local rc=$?
    trap - EXIT
    set +e
    if [ -n "$TEST_DEPLOYMENT_DIR" ] && [ -d "$TEST_DEPLOYMENT_DIR" ]; then
        if [ $rc -ne 0 ]; then
            dump_diagnostics
        fi
        $TEST_TARGET_STACK manage --dir "$TEST_DEPLOYMENT_DIR" stop --delete-volumes
    fi
    if [ -n "$TEST_EXTRA_CLEANUP" ]; then
        $TEST_EXTRA_CLEANUP
    fi
    exit $rc
}

# Report what a failing deployment was doing, before it is torn down.
dump_diagnostics () {
    echo "===================== FAILURE DIAGNOSTICS ====================="
    echo "----- ps -----"
    $TEST_TARGET_STACK manage --dir "$TEST_DEPLOYMENT_DIR" ps || true
    echo "----- container logs (last 200 lines per service) -----"
    $TEST_TARGET_STACK manage --dir "$TEST_DEPLOYMENT_DIR" logs -n 200 || true
    echo "=============================================================="
}

# Run a command inside one of the deployment's containers.  `exec` wraps the
# command in `sh -c`, so the whole command goes in a single argument:
#
#     deployment_exec app "echo hello > /data/file"
deployment_exec () {
    $TEST_TARGET_STACK manage --dir "$TEST_DEPLOYMENT_DIR" exec "$1" "$2"
}

# --- waiting -----------------------------------------------------------------

# Wait until `manage status` reports at least $1 services running.  $2 overrides
# the number of 5-second checks (default 10): against a real cluster the images
# are pulled from a real registry over the network, which can take minutes on a
# cold node, so those tests ask for more.
#
# "status" reports a container as running only once it is actually ready -- on
# k8s once its readiness probes pass -- so this is a readiness wait, not just a
# started wait.
wait_for_running () {
    local how_many=$1
    local check_limit=${2:-10}
    local running=0
    local check=0
    while [ $running -lt $how_many ] && [ $check -lt $check_limit ]; do
        check=$((check + 1))
        # grep -c exits non-zero when the count is zero, which is a normal
        # outcome early on, so do not let it trip `set -e`.
        running=$( $TEST_TARGET_STACK manage --dir "$TEST_DEPLOYMENT_DIR" status | grep -ic "running" ) || true
        if [ $running -lt $how_many ]; then
            echo "waiting for services to start ($running/$how_many)..."
            sleep 5
        fi
    done
    if [ $running -lt $how_many ]; then
        fail "waiting for services to start: FAILED - $running of $how_many running"
    fi
}

# Wait until `manage ps` lists the deployment's containers.  ps prints one
# "id: ..." line per container for both targets (ps_operation in
# src/stack/deploy/deploy.py), so that is the marker to match.  $1 overrides the
# number of 5-second checks (default 50).
wait_for_containers_started () {
    local check_limit=${1:-50}
    local check=0
    local ps_output
    while [ $check -lt $check_limit ]; do
        check=$((check + 1))
        ps_output=$( $TEST_TARGET_STACK manage --dir "$TEST_DEPLOYMENT_DIR" ps )
        if [[ "$ps_output" == *"id:"* ]]; then
            return
        fi
        sleep 5
    done
    fail "waiting for containers to start: FAILED"
}

# Wait until `manage logs` output contains $1 -- or, with no argument, until it
# produces any output at all.  $2 overrides the number of 5-second checks
# (default 50).
wait_for_log_content () {
    local expected=$1
    local check_limit=${2:-50}
    local check=0
    local log_output
    while [ $check -lt $check_limit ]; do
        check=$((check + 1))
        log_output=$( $TEST_TARGET_STACK manage --dir "$TEST_DEPLOYMENT_DIR" logs )
        if [ -z "$expected" ]; then
            if [ -n "$log_output" ]; then
                return
            fi
        elif [[ "$log_output" == *"$expected"* ]]; then
            return
        fi
        sleep 5
    done
    fail "waiting for log content '${expected}': FAILED"
}

# Fetch $1 until its body contains $2.  $3 overrides the number of 5-second
# attempts (default 20).
#
# A container being ready is not the same as its server being ready to serve --
# and on k8s the ingress/gateway needs a moment to route to the new endpoints --
# so a single-shot fetch here is a race.  The last response body is printed on
# failure, without which a CI log says only that the text was not found.
wait_for_content () {
    local url=$1
    local expected=$2
    local tries=${3:-20}
    local try=0
    local body=""
    while [ $try -lt $tries ]; do
        try=$((try + 1))
        body=$( curl -s "$url" ) || true
        if echo "$body" | grep -q "$expected"; then
            return
        fi
        echo "Waiting for $expected at $url..."
        sleep 5
    done
    echo "last response body was:"
    echo "$body"
    fail "http: FAILED - $expected not found at $url"
}
