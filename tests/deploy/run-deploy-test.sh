#!/usr/bin/env bash
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

require_commands jq

add_todo() {
  set +e

  url=$1
  title=$2

  try=0
  rc=1

  while [ $rc -ne 0 ] && [ $try -lt 10 ]; do
    try=$((try + 1))
    curl "$url" \
      --fail-with-body \
      -H 'Accept: application/json, text/plain, */*' \
      -H 'Accept-Language: en-US,en;q=0.9' \
      -H 'Connection: keep-alive' \
      -H 'Content-Type: application/json' \
      -H 'Origin: http://localhost' \
      -H 'Referer: http://localhost/' \
      -H 'Sec-Fetch-Dest: empty' \
      -H 'Sec-Fetch-Mode: cors' \
      -H 'Sec-Fetch-Site: same-site' \
      -H 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0' \
      -H 'sec-ch-ua: "Microsoft Edge";v="135", "Not-A.Brand";v="8", "Chromium";v="135"' \
      -H 'sec-ch-ua-mobile: ?0' \
      -H 'sec-ch-ua-platform: "Windows"' \
      --data-raw "{\"title\":\"$title\",\"completed\":false}"
    rc=$?

    if [ $rc -ne 0 ]; then
      echo "Error adding todo, retrying..."
      sleep 5
    fi
  done

  set -e

  return $rc
}

export STACK_USE_BUILTIN_STACK=true

# Test basic stack deploy
echo "Running stack deploy test"
select_test_target "$@"
setup_test_dir deploy-test-dir
# Test bringing the test container up and down
# with and without volume removal

STACK_NAME="todo"

$TEST_TARGET_STACK fetch repo bozemanpass/example-todo-list
$TEST_TARGET_STACK prepare --stack $STACK_NAME

# Basic test of creating a deployment
# Deployment artifacts live outside the repo base dir, so the deployment's copy
# of the stack files is not seen when resolving stacks by name.
test_deployment_dir=$STACK_TEST_DIR/test-deployment-dir
test_deployment_spec=$STACK_TEST_DIR/test-deployment-spec.yml
$TEST_TARGET_STACK init --stack $STACK_NAME --output $test_deployment_spec --map-ports-to-host localhost-same
# Check the file now exists
if [ ! -f "$test_deployment_spec" ]; then
    fail "deploy init test: FAILED - spec file not present"
fi
echo "deploy init test: passed"
stop_deployment_on_exit $test_deployment_dir
$TEST_TARGET_STACK deploy --spec-file $test_deployment_spec --deployment-dir $test_deployment_dir
# Check the deployment dir exists
if [ ! -d "$test_deployment_dir" ]; then
    fail "deploy deploy test: FAILED - deployment directory not present"
fi
echo "deploy create test: passed"

# Start
$TEST_TARGET_STACK manage --dir $test_deployment_dir start
wait_for_running 3

# Add a todo
todo_title="79b06705-b402-431a-83a3-a634392d2754"
add_todo http://localhost:5000 "$todo_title"

# Check that it exists
if [ "$todo_title" != "$(curl -s http://localhost:5000 | jq -r '.[] | select(.id == 1) | .title')" ]; then
    fail "deploy storage: failed - todo $todo_title not found"
fi

# Stop the stack (don't delete volumes)
$TEST_TARGET_STACK manage --dir $test_deployment_dir stop

# Restart the stack
$TEST_TARGET_STACK manage --dir $test_deployment_dir start

# Check that all services are running
wait_for_running 3

# Check that it is still viewable
if [ "$todo_title" != "$(curl -s http://localhost:5000 | jq -r '.[] | select(.id == 1) | .title')" ]; then
    fail "deploy storage: failed - todo $todo_title not found after restart"
fi
echo "deploy storage: passed"

# TODO: Do we need to add a check for deleting the volumes?
#  Docker doesn't remove the files for a bound volume so nothing much really changes.

# The built frontend references its JS bundle as /assets/index-<hash>.js, so
# match the stable prefix rather than the per-build hash.
wait_for_content http://localhost:3000 '/assets/index-'
echo "deploy http: passed"

echo "Test passed"
