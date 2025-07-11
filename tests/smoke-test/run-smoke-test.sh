#!/usr/bin/env bash
set -e
if [ -n "$STACK_SCRIPT_DEBUG" ]; then
  set -x
fi
export STACK_USE_BUILTIN_STACK=true
# Dump environment variables for debugging
echo "Environment variables:"
env
# Basic simple test of stack functionality
echo "Running stack smoke test"
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
# Test building the a stack container
$TEST_TARGET_SO --verbose --debug prepare --stack test
# Build one example containers
$TEST_TARGET_SO --verbose --debug prepare --stack test --include-containers bozemanpass/test-container
echo "Images in the local registry:"
docker image ls -a
test_deployment_dir=$STACK_REPO_BASE_DIR/test-deployment-dir
test_deployment_spec=$STACK_REPO_BASE_DIR/test-deployment-spec.yml
# Deploy the test container
$TEST_TARGET_SO init --stack test --output $test_deployment_spec
$TEST_TARGET_SO deploy --spec-file $test_deployment_spec --deployment-dir $test_deployment_dir
# Up
$TEST_TARGET_SO manage --dir $test_deployment_dir start
# Down
$TEST_TARGET_SO manage --dir $test_deployment_dir stop
# Run same test but not using the stack definition
# Test building the a stack container
$TEST_TARGET_SO build containers --stack test --include bozemanpass/test-container
echo "Test passed"
