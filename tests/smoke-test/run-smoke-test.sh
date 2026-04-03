#!/usr/bin/env bash
set -e
if [ -n "$STACK_SCRIPT_DEBUG" ]; then
  set -x
fi
# Dump environment variables for debugging
echo "Environment variables:"
env
# Basic simple test of stack functionality
echo "Running stack smoke test"
# Bit of a hack, test the most recent package
TEST_TARGET_STACK=$( ls -t1 ./package/stack* | head -1 )
# We make a directory within which our test will create files
STACK_TEST_DIR=~/stack-test/smoke-test-dir
# Set a non-default repo dir
export STACK_REPO_BASE_DIR=${STACK_TEST_DIR}/repo-base-dir
echo "Testing this package: $TEST_TARGET_STACK"
echo "Test version command"
reported_version_string=$( $TEST_TARGET_STACK version )
echo "Version reported is: ${reported_version_string}"
echo "Using test directory: $STACK_TEST_DIR"
echo "Cloning repositories into: $STACK_REPO_BASE_DIR"
rm -rf $STACK_TEST_DIR
mkdir -p $STACK_TEST_DIR
mkdir -p $STACK_REPO_BASE_DIR
# We must delete any instances of the test-container in the local registory
# otherwise we'll skip building it below
existing_test_images=$(docker image ls -q --filter=reference=bozemanpass/test-container | uniq)
if [ -n "$existing_test_images" ]; then
  docker image rm -f ${existing_test_images}
fi
# Fetch the test stacks
$TEST_TARGET_STACK fetch repo github.com/bozemanpass/stack-test-stacks
# Test building the a stack container
$TEST_TARGET_STACK prepare --stack test
# Build one example containers
$TEST_TARGET_STACK prepare --stack test --include-containers bozemanpass/test-container
echo "Images in the local registry:"
docker image ls -a
test_deployment_dir=$STACK_TEST_DIR/test-deployment-dir
test_deployment_spec=$STACK_TEST_DIR/test-deployment-spec.yml
# Deploy the test container
$TEST_TARGET_STACK init --stack test --output $test_deployment_spec
$TEST_TARGET_STACK deploy --spec-file $test_deployment_spec --deployment-dir $test_deployment_dir
# Up
$TEST_TARGET_STACK manage --dir $test_deployment_dir start
# Down
$TEST_TARGET_STACK manage --dir $test_deployment_dir stop
# Run same test but not using the stack definition
# Test building the a stack container
$TEST_TARGET_STACK --debug --verbose build containers --stack test --include bozemanpass/test-container
echo "Test passed"
