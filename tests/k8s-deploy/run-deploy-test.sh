#!/usr/bin/env bash
set -e

if [ -n "$STACK_SCRIPT_DEBUG" ]; then
  set -x
fi

# Check for required utilities
if ! command -v jq &> /dev/null; then
    echo "Error: jq is not installed."
    echo "Please install jq to run this test script."
    exit 1
fi

# Determine if we're testing against a remote k8s cluster
# Set STACK_K8S_REMOTE=true to enable remote mode, which also requires:
#   STACK_KUBE_CONFIG    - path to kubeconfig file
#   STACK_IMAGE_REGISTRY - container image registry URL
#   STACK_K8S_HOSTNAME   - hostname of the remote cluster
if [ "$STACK_K8S_REMOTE" = "true" ]; then
  if [ -z "$STACK_KUBE_CONFIG" ] || [ -z "$STACK_IMAGE_REGISTRY" ] || [ -z "$STACK_K8S_HOSTNAME" ]; then
    echo "Error: Remote k8s mode requires STACK_KUBE_CONFIG, STACK_IMAGE_REGISTRY, and STACK_K8S_HOSTNAME"
    exit 1
  fi
  DEPLOY_TO="k8s"
  TEST_HOSTNAME="$STACK_K8S_HOSTNAME"
  TEST_SCHEME="https"
else
  DEPLOY_TO="k8s-kind"
  TEST_HOSTNAME="localhost"
  TEST_SCHEME="http"
fi

# Dump environment variables for debugging
echo "Environment variables:"
env

delete_cluster_exit () {
  if [ -d "$test_deployment_dir" ]; then
    $TEST_TARGET_SO manage --dir $test_deployment_dir stop --delete-volumes
  fi
}

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
      -H "Origin: ${TEST_SCHEME}://${TEST_HOSTNAME}" \
      -H "Referer: ${TEST_SCHEME}://${TEST_HOSTNAME}/" \
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

# Test basic stack deploy
echo "Running stack deploy test"
# Bit of a hack, test the most recent package
TEST_TARGET_SO=$( ls -t1 ./package/stack* | head -1 )
# We make a directory within which our test will create files
STACK_TEST_DIR=~/stack-test/k8s-test-dir
# Set a non-default repo dir
export STACK_REPO_BASE_DIR=${STACK_TEST_DIR}/repo-base-dir
echo "Testing this package: $TEST_TARGET_SO"
echo "Test version command"
reported_version_string=$( $TEST_TARGET_SO version )
echo "Version reported is: ${reported_version_string}"
echo "Cloning repositories into: $STACK_REPO_BASE_DIR"
rm -rf $STACK_TEST_DIR
mkdir -p $STACK_TEST_DIR
mkdir -p $STACK_REPO_BASE_DIR
# Test bringing the test container up and down
# with and without volume removal

STACK_NAME="todo"

$TEST_TARGET_SO fetch repo bozemanpass/example-todo-list
$TEST_TARGET_SO prepare --stack $STACK_NAME

# Basic test of creating a deployment
test_deployment_dir=$STACK_TEST_DIR/test-deployment-dir
test_deployment_spec=$STACK_TEST_DIR/test-deployment-spec.yml
init_args="--deploy-to $DEPLOY_TO --stack $STACK_NAME --output $test_deployment_spec"
init_args="$init_args --http-proxy-fqdn $TEST_HOSTNAME"
init_args="$init_args --config REACT_APP_API_URL=${TEST_SCHEME}://${TEST_HOSTNAME}/api/todos"
if [ "$STACK_K8S_REMOTE" = "true" ]; then
  init_args="$init_args --kube-config $STACK_KUBE_CONFIG --image-registry $STACK_IMAGE_REGISTRY"
fi
$TEST_TARGET_SO init $init_args

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

# Push images to remote registry if needed
if [ "$STACK_K8S_REMOTE" = "true" ]; then
  $TEST_TARGET_SO manage --dir $test_deployment_dir push-images
fi

# Start
$TEST_TARGET_SO manage --dir $test_deployment_dir start
wait_for_running 3

# Add a todo
todo_title="79b06705-b402-431a-83a3-a634392d2754"
add_todo ${TEST_SCHEME}://${TEST_HOSTNAME}/api/todos "$todo_title"


# Check that it exists
if [ "$todo_title" != "$(curl -s ${TEST_SCHEME}://${TEST_HOSTNAME}/api/todos | jq -r '.[] | select(.id == 1) | .title')" ]; then
    echo "deploy storage: failed - todo $todo_title not found"
    exit 1
fi

wget -q -O - ${TEST_SCHEME}://${TEST_HOSTNAME} | grep 'bundle.js'
echo "deploy http: passed"

delete_cluster_exit

echo "Test passed"
