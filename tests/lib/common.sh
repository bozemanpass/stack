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

# Containers started via start_container, stopped at exit.
TEST_CONTAINER_IDS=""

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

# --- deployment targets ------------------------------------------------------

# Select the deployment target the test runs against, from STACK_TEST_TARGET:
#
#   compose   Docker Compose on the local machine (the default)
#   kind      a local kind cluster
#   remote    a real k8s cluster elsewhere, described by STACK_KUBE_CONFIG,
#             STACK_IMAGE_REGISTRY and STACK_K8S_HOSTNAME (the k3s cluster
#             harness in tests/k3s-deploy sets all four)
#
# A test that works on more than one target calls this instead of hardcoding a
# --deploy-to, and uses what it sets:
#
#   TEST_TARGET_ENV         the selected target, for the few genuinely
#                           target-shaped decisions a test still has to make
#   TEST_INIT_ARGS          target plumbing for `stack init`: the --deploy-to,
#                           and on a remote cluster the kubeconfig and registry
#   TEST_PROXY_INIT_ARGS    how a test that serves HTTP is reached from outside:
#                           published host ports on compose, the HTTP proxy
#                           hostname on k8s.  Separate from TEST_INIT_ARGS
#                           because a test with no HTTP endpoint should pass
#                           neither (init warns about an --http-proxy-fqdn with
#                           nothing to proxy).
#   TEST_SCHEME             https on a real cluster, which has a real
#   TEST_HOSTNAME           certificate; http on the local targets
#   TEST_START_CHECK_LIMIT  checks to allow for startup, for wait_for_running:
#                           on a cluster the images come from a registry over
#                           the network, which is minutes on a cold node
#
# The point of routing every target difference through here is that the
# per-target divergence of a test stays in one place and stays visible, rather
# than each test growing its own copy.
select_deploy_target () {
    TEST_TARGET_ENV=${STACK_TEST_TARGET:-compose}
    case "$TEST_TARGET_ENV" in
        compose)
            TEST_INIT_ARGS=""
            # localhost-same publishes each declared container port on the same
            # port of the host, so the test reaches services directly.
            TEST_PROXY_INIT_ARGS="--map-ports-to-host localhost-same"
            TEST_SCHEME="http"
            TEST_HOSTNAME="localhost"
            TEST_START_CHECK_LIMIT=10
            ;;
        kind)
            require_commands kind
            TEST_INIT_ARGS="--deploy-to k8s-kind"
            TEST_PROXY_INIT_ARGS="--http-proxy-fqdn localhost"
            TEST_SCHEME="http"
            TEST_HOSTNAME="localhost"
            TEST_START_CHECK_LIMIT=60
            ;;
        remote)
            if [ -z "$STACK_KUBE_CONFIG" ] || [ -z "$STACK_IMAGE_REGISTRY" ] || [ -z "$STACK_K8S_HOSTNAME" ]; then
                fail "Error: the remote target requires STACK_KUBE_CONFIG, STACK_IMAGE_REGISTRY and STACK_K8S_HOSTNAME"
            fi
            TEST_INIT_ARGS="--deploy-to k8s --kube-config $STACK_KUBE_CONFIG --image-registry $STACK_IMAGE_REGISTRY"
            TEST_PROXY_INIT_ARGS="--http-proxy-fqdn $STACK_K8S_HOSTNAME"
            TEST_SCHEME="https"
            TEST_HOSTNAME="$STACK_K8S_HOSTNAME"
            TEST_START_CHECK_LIMIT=60
            ;;
        *)
            fail "Error: STACK_TEST_TARGET must be compose, kind or remote, not $TEST_TARGET_ENV"
            ;;
    esac
    echo "Testing against the $TEST_TARGET_ENV target"
}

# The host's own address, as a container reaches it: the source address the
# kernel would use to leave the machine.  Not 127.0.0.1, which inside a container
# is the container, and not the docker bridge gateway, which differs per network.
host_address () {
    ip -4 route get 1 | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1); exit}'
}

# Configure where backups are written, for the tests that take them.
#
# Backup is configured ambiently -- the stack tool reads STACK_BACKUP* from the
# environment -- so this sets that environment, and the test itself contains no
# backup configuration.  It is separate from select_deploy_target because the
# backup engine differs by target in a way nothing else does:
#
#   compose   the backup stack runs restic, against a SeaweedFS store the test
#             deploys, so everything is local and disposable
#   remote    K8up runs the backups, and it is pointed at a real object store
#             (DigitalOcean Spaces) named by the environment -- so neither the
#             backup container nor a local store is deployed there
#   kind      unsupported: K8up is not installed on a kind cluster, deliberately
#             (nobody runs kind in production, so a backup test there would be
#             testing an arrangement nobody has -- see issue #227)
#
# Pass "external" for a test whose object store has to outlive the deployment
# that wrote to it -- one that destroys a deployment and restores its backup into
# a new one.  It changes nothing on a real cluster, whose store is already
# external, and on the Docker target it moves SeaweedFS out of the deployment and
# into a deployment of its own, reached over a published port rather than by
# service name (see start_object_store_deployment).
#
# Sets, for the test to use:
#
#   TEST_BACKUP_MIX_IN          non-empty if the deployment has to carry the backup
#                               engine itself (the Docker target); empty where the
#                               cluster provides one
#   TEST_BACKUP_EXTRA_SERVICES  how many services the backup arrangement adds to
#                               the deployment, for the startup wait: the test adds
#                               it to its own stack's service count rather than
#                               knowing which target contributes what
#   TEST_BACKUP_STORE_WARMUP    non-empty if the object store is one this test
#                               starts, and so has to be waited for
#   TEST_BACKUP_STORE_STACK     non-empty if the test has to deploy the object
#                               store itself, as a deployment of its own
#   TEST_BACKUP_CAN_SEED        non-empty if a second deployment can read the first
#                               one's backups, so that seeding one deployment from
#                               another can be tested. Only false of a store that
#                               lives inside the first deployment and publishes
#                               nothing, which is what "external" avoids
select_backup_target () {
    local store=${1:-in-deployment}
    export STACK_BACKUP=true
    case "$TEST_TARGET_ENV" in
        compose)
            export STACK_BACKUP_S3_BUCKET=stack-backups
            # Matching the S3 identity the test stack configures SeaweedFS with.
            export STACK_BACKUP_S3_KEY_ID=test-access-key
            export STACK_BACKUP_S3_KEY=test-secret-key
            export STACK_BACKUP_RESTIC_PASSWORD=test-restic-password
            TEST_BACKUP_MIX_IN=yes
            TEST_BACKUP_STORE_WARMUP=yes
            if [ "$store" == "external" ]; then
                # The store is a deployment of its own, publishing its port on
                # every interface, so the backup container in another deployment
                # reaches it at the host's address.  Not "localhost": that is the
                # container itself, and not the service name either, since the two
                # deployments are on separate docker networks.
                export STACK_BACKUP_S3_ENDPOINT=http://$( host_address ):8333
                TEST_BACKUP_EXTRA_SERVICES=1
                TEST_BACKUP_STORE_STACK=yes
                TEST_BACKUP_CAN_SEED=yes
            else
                export STACK_BACKUP_S3_ENDPOINT=http://s3:8333
                TEST_BACKUP_EXTRA_SERVICES=2
                TEST_BACKUP_STORE_STACK=
                TEST_BACKUP_CAN_SEED=
            fi
            ;;
        remote)
            if [ -z "$STACK_BACKUP_S3_BUCKET" ] || [ -z "$STACK_BACKUP_S3_KEY_ID" ] || [ -z "$STACK_BACKUP_S3_KEY" ]; then
                fail "Error: the backup test on a real cluster requires STACK_BACKUP_S3_BUCKET, STACK_BACKUP_S3_KEY_ID and STACK_BACKUP_S3_KEY"
            fi
            # A Spaces bucket is handed out as a URL with the bucket as the first
            # label (https://<bucket>.<region>.digitaloceanspaces.com), while the
            # tool wants the endpoint and the bucket separately.  Accept either.
            if [ -z "$STACK_BACKUP_S3_ENDPOINT" ]; then
                case "$STACK_BACKUP_S3_BUCKET" in
                    https://*|http://*)
                        _scheme="${STACK_BACKUP_S3_BUCKET%%://*}"
                        _host="${STACK_BACKUP_S3_BUCKET#*://}"
                        _host="${_host%%/*}"
                        export STACK_BACKUP_S3_BUCKET="${_host%%.*}"
                        export STACK_BACKUP_S3_ENDPOINT="${_scheme}://${_host#*.}"
                        ;;
                    *)
                        fail "Error: set STACK_BACKUP_S3_ENDPOINT, or give STACK_BACKUP_S3_BUCKET as the bucket's URL"
                        ;;
                esac
            fi
            # Each deployment writes its own restic repository, which the tool
            # names for the deployment inside the bucket -- so runs cannot collide
            # and a password supplied here is not shared with anything else.
            #
            # Supply one (CI does) and the repositories a run leaves behind stay
            # readable afterwards, which is what makes them usable later: to
            # restore one by hand, or as the fixture for a test that restores a
            # backup an earlier run took. Without one this falls back to a
            # password that exists only for the length of the run, and its
            # repository becomes unreadable the moment the run ends -- correct
            # for a throwaway local run, useless to keep.
            export STACK_BACKUP_RESTIC_PASSWORD=${STACK_BACKUP_RESTIC_PASSWORD:-backup-test-$$}
            TEST_BACKUP_MIX_IN=""
            TEST_BACKUP_EXTRA_SERVICES=0
            TEST_BACKUP_STORE_WARMUP=""
            TEST_BACKUP_STORE_STACK=""
            TEST_BACKUP_CAN_SEED=yes
            ;;
        *)
            fail "Error: the backup test does not support the $TEST_TARGET_ENV target (K8up, which runs backups on k8s, is not installed on a kind cluster)"
            ;;
    esac
    echo "Backing up to ${STACK_BACKUP_S3_ENDPOINT}/${STACK_BACKUP_S3_BUCKET}"
}

# Deploy the object store as a deployment of its own, for a test that asked
# select_backup_target for an "external" store.  A no-op where the store is
# already external -- a real cluster's is.
#
# It is a separate deployment rather than a mix-in precisely so that it survives
# the deployment under test being destroyed: a store that lives inside the
# deployment holding the data goes down with it, taking the backup along and
# leaving nothing to restore from.  Its ports are published on every interface so
# that the backup container of *another* deployment, on another docker network,
# can reach it at the host's address (see select_backup_target).
#
# Registered as the extra cleanup, so it is stopped however the test ends.  A test
# with cleanup of its own therefore does not get to use TEST_EXTRA_CLEANUP.
#
# The store is the test-s3-stack from the stack-test-stacks repo, so the caller
# has to have fetched that already -- every test needing a store fetches it for
# its own stack anyway.
start_object_store_deployment () {
    if [ -z "$TEST_BACKUP_STORE_STACK" ]; then
        return
    fi
    local store_stack="test-s3-stack"
    local store_spec=$STACK_TEST_DIR/${store_stack}-spec.yml
    TEST_OBJECT_STORE_DIR=$STACK_TEST_DIR/${store_stack}-deployment

    $TEST_TARGET_STACK prepare --stack ${store_stack}
    # The store is not itself a thing under backup: it holds the backups.
    STACK_BACKUP=false $TEST_TARGET_STACK init --stack ${store_stack} \
        --map-ports-to-host any-same --output "$store_spec"
    STACK_BACKUP=false $TEST_TARGET_STACK deploy --spec-file "$store_spec" \
        --deployment-dir "$TEST_OBJECT_STORE_DIR"
    TEST_EXTRA_CLEANUP=stop_object_store_deployment
    $TEST_TARGET_STACK manage --dir "$TEST_OBJECT_STORE_DIR" start
    echo "object store deployed at ${STACK_BACKUP_S3_ENDPOINT}"
}

stop_object_store_deployment () {
    $TEST_TARGET_STACK manage --dir "$TEST_OBJECT_STORE_DIR" stop --delete-volumes
}

# Wait until the object store backups go to can serve back what it accepts.
#
# Only the store this test starts itself needs this, and it needs it for a reason
# worth stating: a SeaweedFS that has just started accepts a restic repository and
# then serves something else for the reads, which leaves a repository that can
# never be read -- restic will not initialize over it, so every later attempt fails
# on "already initialized". Waiting for a container to be "running", or for the
# store to answer HTTP, is not enough; the only question that distinguishes a store
# that is ready is whether it reads back what it just wrote, so that is what this
# asks, in a throwaway repository.
#
# A real object store is always ready, so this is skipped where the store is one.
wait_for_backup_store () {
    if [ -z "$TEST_BACKUP_STORE_WARMUP" ]; then
        return
    fi
    local check_limit=${1:-24}
    local check=0
    while [ $check -lt $check_limit ]; do
        check=$((check + 1))
        # Each probe uses a repository of its own: a damaged one stays damaged, so
        # probing the same path twice would report the first failure forever.
        if deployment_exec backup "probe=s3:\${BACKUP_S3_ENDPOINT}/\${BACKUP_S3_BUCKET}-probe-${check}; \
                restic -r \$probe init > /dev/null 2>&1 && restic -r \$probe cat config > /dev/null 2>&1"; then
            return
        fi
        echo "waiting for the object store to become ready..."
        sleep 5
    done
    fail "waiting for the object store: FAILED"
}

# Push the deployment's images to the registry the cluster pulls from.  Only a
# remote cluster needs this: compose runs the images from the local daemon, and
# kind loads them into its nodes itself.
push_images_if_needed () {
    if [ "$TEST_TARGET_ENV" == "remote" ]; then
        $TEST_TARGET_STACK manage --dir "$1" push-images
    fi
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
    if [ -n "$TEST_CONTAINER_IDS" ]; then
        docker stop $TEST_CONTAINER_IDS > /dev/null 2>&1
    fi
    if [ -n "$TEST_EXTRA_CLEANUP" ]; then
        $TEST_EXTRA_CLEANUP
    fi
    exit $rc
}

# Start a container with `docker run` and remember it, setting CONTAINER_ID.
# Pass the usual docker run arguments:
#
#     start_container -p 3000:80 -d "$image"
#
# The container is stopped at exit however the test ends. Without that, a test
# that fails mid-way leaves its port bound and the *next* test fails with a
# confusing "port is already allocated". Stopping it by hand earlier is fine.
start_container () {
    CONTAINER_ID=$( docker run "$@" )
    TEST_CONTAINER_IDS="$TEST_CONTAINER_IDS $CONTAINER_ID"
    trap _test_exit_handler EXIT
}

# Destroy a deployment completely: stop it, delete its volumes, and remove the
# deployment directory, so that nothing of it is left for a later step to lean on
# by accident.  For a test whose point is that something survives the deployment
# that produced it -- a backup taken from a deployment that is then destroyed --
# a half-removed deployment is the way that test passes for the wrong reason.
#
# The exit-time teardown is dropped along with it, so a test destroying the
# deployment the helpers are pointed at should point them at its replacement with
# stop_deployment_on_exit.
destroy_deployment () {
    $TEST_TARGET_STACK manage --dir "$1" stop --delete-volumes
    force_rm "$1"
    if [ "$TEST_DEPLOYMENT_DIR" == "$1" ]; then
        TEST_DEPLOYMENT_DIR=""
    fi
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

# Wait until the deployment's containers are gone, after a stop.  $1 overrides
# the number of 5-second checks (default 24, so two minutes).
#
# `stop` returns once it has deleted the objects, not once they are gone. On a
# real cluster a pod terminates gracefully and lingers for a while, and both `ps`
# and `logs` keep reporting it -- so a test that stops, starts, and then waits
# for a log line can match the *previous* run's output from a pod that is on its
# way out, and carry on before the new one has done anything at all. That is a
# race the local targets usually win and a real cluster usually loses.
wait_for_stopped () {
    local check_limit=${1:-24}
    local check=0
    local ps_output
    while [ $check -lt $check_limit ]; do
        check=$((check + 1))
        ps_output=$( $TEST_TARGET_STACK manage --dir "$TEST_DEPLOYMENT_DIR" ps ) || true
        if [[ "$ps_output" != *"id:"* ]]; then
            return
        fi
        echo "waiting for containers to stop..."
        sleep 5
    done
    fail "waiting for containers to stop: FAILED"
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

# POST a todo to the example todo app serving at $1, retrying until it is
# accepted.  $3 is the origin the request claims to come from -- the app's CORS
# handling rejects a mismatch, so it is "http://localhost" for a compose
# deployment and the scheme+host of the cluster for k8s.
#
# The browser-shaped headers are deliberate: the app is fronted by CORS and
# content-type checks, and a bare curl does not get past them.
add_todo () {
    local url=$1
    local title=$2
    local origin=$3
    local try=0
    local rc=1

    while [ $rc -ne 0 ] && [ $try -lt 10 ]; do
        try=$((try + 1))
        rc=0
        curl "$url" \
          --fail-with-body \
          -H 'Accept: application/json, text/plain, */*' \
          -H 'Accept-Language: en-US,en;q=0.9' \
          -H 'Connection: keep-alive' \
          -H 'Content-Type: application/json' \
          -H "Origin: ${origin}" \
          -H "Referer: ${origin}/" \
          -H 'Sec-Fetch-Dest: empty' \
          -H 'Sec-Fetch-Mode: cors' \
          -H 'Sec-Fetch-Site: same-site' \
          -H 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0' \
          -H 'sec-ch-ua: "Microsoft Edge";v="135", "Not-A.Brand";v="8", "Chromium";v="135"' \
          -H 'sec-ch-ua-mobile: ?0' \
          -H 'sec-ch-ua-platform: "Windows"' \
          --data-raw "{\"title\":\"$title\",\"completed\":false}" || rc=$?

        if [ $rc -ne 0 ]; then
            echo "Error adding todo, retrying..."
            sleep 5
        fi
    done

    if [ $rc -ne 0 ]; then
        fail "add todo: FAILED - could not add '$title' at $url"
    fi
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

# --- fetching and asserting --------------------------------------------------

# Fetch $1 into the file $2, retrying while the server comes up.  Any further
# arguments are passed to wget (e.g. -m to follow links, so that an assertion can
# look at content the page pulls in rather than just the page itself).
#
# Returns wget's exit status instead of aborting, so a caller that expects a
# fetch to fail can capture it:
#
#     rc=0; fetch_url "$url" out.html || rc=$?
fetch_url () {
    local url=$1
    local out=$2
    shift 2
    wget --tries 20 --retry-connrefused --waitretry=3 -O "$out" "$@" "$url"
}

# Assert that $2 (an extended regular expression) appears in the file $1,
# reporting "<label>: PASSED" or failing the test.  The file is printed on
# failure -- what the server actually returned is the first thing anyone reading
# a CI log wants.
assert_file_contains () {
    local file=$1
    local pattern=$2
    local label=$3
    if grep -Eq "$pattern" "$file"; then
        echo "${label}: PASSED"
    else
        echo "content of ${file} was:"
        cat "$file"
        fail "${label}: FAILED - '${pattern}' not found in ${file}"
    fi
}

# Assert that $2 does NOT appear in the file $1.
assert_file_not_contains () {
    local file=$1
    local pattern=$2
    local label=$3
    if grep -Eq "$pattern" "$file"; then
        echo "content of ${file} was:"
        cat "$file"
        fail "${label}: FAILED - '${pattern}' unexpectedly found in ${file}"
    else
        echo "${label}: PASSED"
    fi
}

# Assert that $1 is not served -- fetching it must fail.  Call this while the
# server is still up, or it passes for the wrong reason.  A single attempt: the
# expected outcome is an immediate refusal from a server known to be running.
assert_url_not_served () {
    local url=$1
    local label=$2
    if wget -q --tries 1 -O /dev/null "$url"; then
        fail "${label}: FAILED - ${url} was served but should not be"
    fi
    echo "${label}: PASSED"
}
