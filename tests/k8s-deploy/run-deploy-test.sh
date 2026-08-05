#!/usr/bin/env bash
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

require_commands jq

# Determine if we're testing against a remote k8s cluster
# Set STACK_K8S_REMOTE=true to enable remote mode, which also requires:
#   STACK_KUBE_CONFIG    - path to kubeconfig file
#   STACK_IMAGE_REGISTRY - container image registry URL
#   STACK_K8S_HOSTNAME   - hostname of the remote cluster
if [ "$STACK_K8S_REMOTE" = "true" ]; then
  if [ -z "$STACK_KUBE_CONFIG" ] || [ -z "$STACK_IMAGE_REGISTRY" ] || [ -z "$STACK_K8S_HOSTNAME" ]; then
    fail "Error: Remote k8s mode requires STACK_KUBE_CONFIG, STACK_IMAGE_REGISTRY, and STACK_K8S_HOSTNAME"
  fi
  DEPLOY_TO="k8s"
  TEST_HOSTNAME="$STACK_K8S_HOSTNAME"
  TEST_SCHEME="https"
else
  DEPLOY_TO="k8s-kind"
  TEST_HOSTNAME="localhost"
  TEST_SCHEME="http"
fi

# Whether kind or a real cluster, the images are pulled over the network, which
# can take minutes on a cold node, so allow ~5 minutes for services to come up.
START_CHECK_LIMIT=60

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
select_test_target "$@"
setup_test_dir k8s-test-dir
# Test bringing the test container up and down
# with and without volume removal

STACK_NAME="todo"

$TEST_TARGET_STACK fetch repo bozemanpass/example-todo-list
$TEST_TARGET_STACK prepare --stack $STACK_NAME

# Basic test of creating a deployment
test_deployment_dir=$STACK_TEST_DIR/test-deployment-dir
test_deployment_spec=$STACK_TEST_DIR/test-deployment-spec.yml
init_args="--deploy-to $DEPLOY_TO --stack $STACK_NAME --output $test_deployment_spec"
init_args="$init_args --http-proxy-fqdn $TEST_HOSTNAME"
init_args="$init_args --config REACT_APP_API_URL=${TEST_SCHEME}://${TEST_HOSTNAME}/api/todos"
if [ "$STACK_K8S_REMOTE" = "true" ]; then
  init_args="$init_args --kube-config $STACK_KUBE_CONFIG --image-registry $STACK_IMAGE_REGISTRY"
fi
$TEST_TARGET_STACK init $init_args

# Check the file now exists
if [ ! -f "$test_deployment_spec" ]; then
    fail "deploy init test: FAILED - spec file not present"
fi
echo "deploy init test: passed"
stop_deployment_on_exit $test_deployment_dir
$TEST_TARGET_STACK deploy --spec-file $test_deployment_spec --deployment-dir $test_deployment_dir
# Check the deployment dir exists
if [ ! -d "$test_deployment_dir" ]; then
    fail "deploy create test: FAILED - deployment directory not present"
fi
echo "deploy create test: passed"

# Push images to remote registry if needed
if [ "$STACK_K8S_REMOTE" = "true" ]; then
  $TEST_TARGET_STACK manage --dir $test_deployment_dir push-images
fi

# Start
$TEST_TARGET_STACK manage --dir $test_deployment_dir start
wait_for_running 3 $START_CHECK_LIMIT

# Add a todo
todo_title="79b06705-b402-431a-83a3-a634392d2754"
add_todo ${TEST_SCHEME}://${TEST_HOSTNAME}/api/todos "$todo_title"

# Check that it exists
if [ "$todo_title" != "$(curl -s ${TEST_SCHEME}://${TEST_HOSTNAME}/api/todos | jq -r '.[] | select(.id == 1) | .title')" ]; then
    fail "deploy storage: failed - todo $todo_title not found"
fi

# The built frontend references its JS bundle as /assets/index-<hash>.js, so
# match the stable prefix rather than the per-build hash.
wait_for_content ${TEST_SCHEME}://${TEST_HOSTNAME} '/assets/index-'
echo "deploy http: passed"

echo "Test passed"
