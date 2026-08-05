#!/usr/bin/env bash
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

# Test basic stack webapp
echo "Running stack webapp test"
select_test_target "$@"
setup_test_dir webapp-test-dir
echo "Cloning repositories into: $STACK_REPO_BASE_DIR"
git clone https://github.com/bozemanpass/test-progressive-web-app.git $STACK_REPO_BASE_DIR/test-progressive-web-app

# Test webapp command execution
$TEST_TARGET_STACK webapp build --source-repo $STACK_REPO_BASE_DIR/test-progressive-web-app

CHECK="SPECIAL_01234567890_TEST_STRING"

set +e

app_image_name="bozemanpass/test-progressive-web-app:stack"

CONTAINER_ID=$(docker run -p 3000:80 -d -e STACK_SCRIPT_DEBUG=$STACK_SCRIPT_DEBUG ${app_image_name})
if [ $? -ne 0 ]; then
  echo "Failed to start container from image ${app_image_name}"
  exit 1
fi
sleep 3
wget --tries 20 --retry-connrefused --waitretry=3 -O test.before -m http://localhost:3000

docker logs $CONTAINER_ID
if [ $? -ne 0 ]; then
  echo "Failed to get logs from container ${CONTAINER_ID}"
  exit 1
fi
docker stop $CONTAINER_ID
if [ $? -ne 0 ]; then
  echo "Failed to stop container ${CONTAINER_ID}"
  exit 1
fi

echo "Running app container test"
CONTAINER_ID=$(docker run -p 3000:80 -e CERC_WEBAPP_DEBUG=$CHECK -e STACK_SCRIPT_DEBUG=$STACK_SCRIPT_DEBUG -d ${app_image_name})
if [ $? -ne 0 ]; then
  echo "Failed to start container from image ${app_image_name}"
  exit 1
fi
sleep 3
wget --tries 20 --retry-connrefused --waitretry=3 -O test.after -m http://localhost:3000

docker logs $CONTAINER_ID
if [ $? -ne 0 ]; then
  echo "Failed to get logs from container ${CONTAINER_ID}"
  exit 1
fi
docker stop $CONTAINER_ID
if [ $? -ne 0 ]; then
  echo "Failed to stop container ${CONTAINER_ID}"
  exit 1
fi

echo "###########################################################################"
echo ""

grep "$CHECK" test.before > /dev/null
if [ $? -ne 1 ]; then
  echo "BEFORE: FAILED"
  exit 1
else
  echo "BEFORE: PASSED"
fi

grep "$CHECK" test.after > /dev/null
if [ $? -ne 0 ]; then
  echo "AFTER: FAILED"
  exit 1
else
  echo "AFTER: PASSED"
fi

echo "Running deployment create test"
# Note: this is not a full test -- all we're testing here is that the webapp deploy command doesn't crash
test_deployment_dir=$STACK_REPO_BASE_DIR/test-deployment-dir
fake_k8s_config_file=$STACK_REPO_BASE_DIR/kube-config.yml
touch ${fake_k8s_config_file}

$TEST_TARGET_STACK webapp deploy --kube-config ${fake_k8s_config_file} --deployment-dir ${test_deployment_dir} --image ${app_image_name} --url https://my-test-app.example.com
if [ -d ${test_deployment_dir} ]; then
  echo "PASSED"
else
  echo "FAILED"
  exit 1
fi

exit 0
