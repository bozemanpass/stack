#!/usr/bin/env bash
set -e

if [ -n "$BPI_SCRIPT_DEBUG" ]; then
  set -x
fi

# Dump environment variables for debugging
echo "Environment variables:"
env

delete_cluster_exit () {
  if [ -d "$test_deployment_dir" ]; then
    $TEST_TARGET_SO manage --dir $test_deployment_dir stop --delete-volumes
  fi
}

trap delete_cluster_exit EXIT

wait_for_pods_started () {
    for i in {1..50}
    do
        local ps_output=$( $TEST_TARGET_SO manage --dir $test_deployment_dir ps )

        if [[ "$ps_output" == *"Running containers:"* ]]; then
            # if ready, return
            return
        else
            # if not ready, wait
            sleep 5
        fi
    done
    # Timed out, error exit
    echo "waiting for pods to start: FAILED"
    exit 1
}

wait_for_log_output () {
    for i in {1..50}
    do

        local log_output=$( $TEST_TARGET_SO manage --dir $test_deployment_dir logs )

        if [[ ! -z "$log_output" ]]; then
            # if ready, return
            return
        else
            # if not ready, wait
            sleep 5
        fi
    done
    # Timed out, error exit
    echo "waiting for pods log content: FAILED"
    exit 1
}

wait_for_running () {
  set +e

  # Check that all services are running
  how_many=$1
  local running=0
  local check=0
  local check_limit=10
  while [ $running -lt $how_many ] && [ $check -lt $check_limit ]; do
      check=$((check + 1))
      running=$($TEST_TARGET_SO manage --dir $test_deployment_dir status | grep -ic "running")
      if [ $running -lt $how_many ]; then
          echo "deploy manage start: Waiting for services to start..."
          sleep 5
      fi
  done

  if [ $running -lt $how_many ]; then
      echo "deploy manage start: failed - not all services started"
      exit 1
  fi

  set -e
}

add_todo() {
  set +e

  local running=0
  local check=0
  local check_limit=10

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
# Bit of a hack, test the most recent package
TEST_TARGET_SO=$( ls -t1 ./package/stack* | head -1 )
# Set a non-default repo dir
export BPI_REPO_BASE_DIR=~/stack-test/repo-base-dir
echo "Testing this package: $TEST_TARGET_SO"
echo "Test version command"
reported_version_string=$( $TEST_TARGET_SO version )
echo "Version reported is: ${reported_version_string}"
echo "Cloning repositories into: $BPI_REPO_BASE_DIR"
rm -rf $BPI_REPO_BASE_DIR
mkdir -p $BPI_REPO_BASE_DIR
# Test bringing the test container up and down
# with and without volume removal

STACK_NAME="example-todo-list"
STACK_PATH="$BPI_REPO_BASE_DIR/$STACK_NAME/stacks/todo"

$TEST_TARGET_SO fetch stack bozemanpass/$STACK_NAME
$TEST_TARGET_SO fetch repositories --stack $STACK_PATH
$TEST_TARGET_SO build containers --stack $STACK_PATH

# Basic test of creating a deployment
test_deployment_dir=$BPI_REPO_BASE_DIR/test-deployment-dir
test_deployment_spec=$BPI_REPO_BASE_DIR/test-deployment-spec.yml
$TEST_TARGET_SO config --deploy-to k8s-kind init \
  --stack $STACK_PATH \
  --output $test_deployment_spec \
  --http-proxy localhost:frontend:3000 \
  --http-proxy localhost/api/todos:backend:5000 \
  --config REACT_APP_API_URL=http://localhost/api/todos

# Check the file now exists
if [ ! -f "$test_deployment_spec" ]; then
    echo "deploy config init test: spec file not present"
    echo "deploy config init test: FAILED"
    exit 1
fi
echo "deploy init test: passed"
$TEST_TARGET_SO deploy --spec-file $test_deployment_spec --deployment-dir $test_deployment_dir
# Check the deployment dir exists
if [ ! -d "$test_deployment_dir" ]; then
    echo "deploy deploy test: deployment directory not present"
    echo "deploy deploy test: FAILED"
    exit 1
fi
echo "deploy create test: passed"

# Start
$TEST_TARGET_SO manage --dir $test_deployment_dir start
wait_for_running 3

# Add a todo
todo_title="79b06705-b402-431a-83a3-a634392d2754"
add_todo http://localhost/api/todos "$todo_title"

# Check that it exists
if [ "$todo_title" != "$(curl -s http://localhost/api/todos | jq -r '.[] | select(.id == 1) | .title')" ]; then
    echo "deploy storage: failed - todo $todo_title not found"
    exit 1
fi

# Stop the stack (don't delete volumes)
$TEST_TARGET_SO manage --dir $test_deployment_dir stop

# Restart the stack
$TEST_TARGET_SO manage --dir $test_deployment_dir start

# Check that all services are running
wait_for_running 3

# Check that it is still viewable
if [ "$todo_title" != "$(curl -s http://localhost/api/todos | jq -r '.[] | select(.id == 1) | .title')" ]; then
    echo "deploy storage: failed - todo $todo_title not found after restart"
    exit 1
fi
echo "deploy storage: passed"

# TODO: Do we need to add a check for deleting the volumes?
#  Docker doesn't remove the files for a bound volume so nothing much really changes.

# Stop and clean up
$TEST_TARGET_SO manage --dir $test_deployment_dir stop --delete-volumes
echo "Test passed"
