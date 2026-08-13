#!/usr/bin/env bash
#
# Deploy the example todo app and check that it works: the API stores a todo,
# the todo survives a stop/start of the deployment, and the frontend is served.
#
# Runs against any of the three deployment targets (see select_deploy_target in
# tests/lib/common.sh); STACK_TEST_TARGET picks which:
#
#   STACK_TEST_TARGET=compose ./tests/app-deploy/run-test.sh   # the default
#   STACK_TEST_TARGET=kind    ./tests/app-deploy/run-test.sh
#   STACK_TEST_TARGET=remote  ./tests/app-deploy/run-test.sh   # see tests/k3s-deploy
#
# This was two scripts, tests/deploy and tests/k8s-deploy, that had drifted into
# testing slightly different things (only the compose one checked that data
# survived a restart, only the k8s one waited long enough for a registry pull).
# The targets differ in how the app is reached and, on k8s, in the frontend
# needing to be told the proxied API URL; everything else is now shared.
#
# Optional environment:
#   STACK_TEST_BUILTIN_STACK  "true" resolves the stack from the tool's builtin
#                             definitions rather than the stack.yml in the app
#                             repo.  Orthogonal to the target; the compose CI
#                             job sets it, which is where that path has always
#                             been covered.
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

require_commands jq

select_test_target "$@"
select_deploy_target

if [ "$STACK_TEST_BUILTIN_STACK" == "true" ]; then
    export STACK_USE_BUILTIN_STACK=true
fi

STACK_NAME="todo"

echo "Running stack deploy test"
setup_test_dir app-deploy-test-dir

$TEST_TARGET_STACK fetch repo bozemanpass/example-todo-list
$TEST_TARGET_STACK prepare --stack $STACK_NAME

# Deployment artifacts live outside the repo base dir, so the deployment's copy
# of the stack files is not seen when resolving stacks by name.
test_deployment_dir=$STACK_TEST_DIR/test-deployment-dir
test_deployment_spec=$STACK_TEST_DIR/test-deployment-spec.yml

# On compose the services are published on the host, so the API and the frontend
# are reached on their own ports.  On k8s both sit behind the HTTP proxy on one
# hostname, and the frontend has to be told where the API ended up.
init_config_args=""
if [ "$TEST_TARGET_ENV" == "compose" ]; then
    api_url=${TEST_SCHEME}://${TEST_HOSTNAME}:5000
    app_url=${TEST_SCHEME}://${TEST_HOSTNAME}:3000
else
    api_url=${TEST_SCHEME}://${TEST_HOSTNAME}/api/todos
    app_url=${TEST_SCHEME}://${TEST_HOSTNAME}
    init_config_args="--config REACT_APP_API_URL=${api_url}"
fi
# The app's CORS handling rejects a request whose origin is not the host it is
# served from, so the origin never carries a port.
origin=${TEST_SCHEME}://${TEST_HOSTNAME}

$TEST_TARGET_STACK init \
    --stack $STACK_NAME \
    --output $test_deployment_spec \
    $TEST_INIT_ARGS \
    $TEST_PROXY_INIT_ARGS \
    $init_config_args

# Check the file now exists
if [ ! -f "$test_deployment_spec" ]; then
    fail "deploy init test: FAILED - spec file not present"
fi
echo "deploy init test: passed"

# The restart check below stops and starts the deployment. On kind that deletes
# and recreates the cluster, taking any volume stored inside it, so the app's
# database has to be mapped onto the host for the data to survive.
if [ "$TEST_TARGET_ENV" == "kind" ]; then
    map_volume_to_host_path "$test_deployment_spec" db-data "${test_deployment_dir}/data/db-data"
fi

stop_deployment_on_exit $test_deployment_dir
$TEST_TARGET_STACK deploy --spec-file $test_deployment_spec --deployment-dir $test_deployment_dir
# Check the deployment dir exists
if [ ! -d "$test_deployment_dir" ]; then
    fail "deploy create test: FAILED - deployment directory not present"
fi
echo "deploy create test: passed"

push_images_if_needed $test_deployment_dir

$TEST_TARGET_STACK manage --dir $test_deployment_dir start
wait_for_running 3 $TEST_START_CHECK_LIMIT

# Add a todo
todo_title="79b06705-b402-431a-83a3-a634392d2754"
add_todo "$api_url" "$todo_title" "$origin"

# Check that it exists
if [ "$todo_title" != "$(curl -s $api_url | jq -r '.[] | select(.id == 1) | .title')" ]; then
    fail "deploy storage: FAILED - todo $todo_title not found"
fi

# Stop and restart the stack without deleting volumes, and check the todo is
# still there: the data outlives the containers on every target, but by quite
# different means (a docker volume, a kind host mount, a real PVC).
$TEST_TARGET_STACK manage --dir $test_deployment_dir stop
$TEST_TARGET_STACK manage --dir $test_deployment_dir start
wait_for_running 3 $TEST_START_CHECK_LIMIT

# The API is served again before the proxy has necessarily caught up with the
# new endpoints, so retry rather than fetching once.
wait_for_content "$api_url" "$todo_title"
echo "deploy storage: passed"

# The built frontend references its JS bundle as /assets/index-<hash>.js, so
# match the stable prefix rather than the per-build hash.
wait_for_content "$app_url" '/assets/index-'
echo "deploy http: passed"

echo "Test passed"
