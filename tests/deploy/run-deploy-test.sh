#!/usr/bin/env bash
set -e
if [ -n "$STACK_SCRIPT_DEBUG" ]; then
  set -x
fi
# Dump environment variables for debugging
echo "Environment variables:"
env

delete_cluster_exit () {
    $TEST_TARGET_SO manage --dir $test_deployment_dir stop --delete-volumes
}

trap delete_cluster_exit EXIT

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


wait_for_running () {
  # Check that all services are running
  local how_many=$1
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
}

export STACK_USE_BUILTIN_STACK=true

# Test basic stack deploy
echo "Running stack deploy test"
# Bit of a hack, test the most recent package
TEST_TARGET_SO=$( ls -t1 ./package/stack* | head -1 )
# Set a non-default repo dir
export STACK_REPO_BASE_DIR=~/stack-test/repo-base-dir
echo "Testing this package: $TEST_TARGET_SO"
echo "Test version command"
reported_version_string=$( $TEST_TARGET_SO version )
echo "Version reported is: ${reported_version_string}"
echo "Cloning repositories into: $STACK_REPO_BASE_DIR"
rm -rf $STACK_REPO_BASE_DIR
mkdir -p $STACK_REPO_BASE_DIR
# Test bringing the test container up and down
# with and without volume removal

STACK_NAME="todo"

$TEST_TARGET_SO fetch stack bozemanpass/example-todo-list
$TEST_TARGET_SO fetch repositories --stack $STACK_NAME
$TEST_TARGET_SO build containers --stack $STACK_NAME

# Basic test of creating a deployment
test_deployment_dir=$STACK_REPO_BASE_DIR/test-deployment-dir
test_deployment_spec=$STACK_REPO_BASE_DIR/test-deployment-spec.yml
$TEST_TARGET_SO init --stack $STACK_NAME --output $test_deployment_spec --map-ports-to-host localhost-same
# Check the file now exists
if [ ! -f "$test_deployment_spec" ]; then
    echo "deploy init test: spec file not present"
    echo "deploy init test: FAILED"
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
add_todo http://localhost:5000/api/todos "$todo_title"

# Check that it exists
if [ "$todo_title" != "$(curl -s http://localhost:5000/api/todos | jq -r '.[] | select(.id == 1) | .title')" ]; then
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
if [ "$todo_title" != "$(curl -s http://localhost:5000/api/todos | jq -r '.[] | select(.id == 1) | .title')" ]; then
    echo "deploy storage: failed - todo $todo_title not found after restart"
    exit 1
fi
echo "deploy storage: passed"

# TODO: Do we need to add a check for deleting the volumes?
#  Docker doesn't remove the files for a bound volume so nothing much really changes.

wget -q -O - http://localhost:3000 | grep 'bundle.js'
echo "deploy http: passed"

echo "Test passed"
