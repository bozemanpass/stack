#!/usr/bin/env bash
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

# Basic simple test of stack functionality
echo "Running stack smoke test"
select_test_target "$@"
setup_test_dir smoke-test-dir
# We must delete any instances of the test-container in the local registory
# otherwise we'll skip building it below
remove_local_images bozemanpass/test-container
# Fetch the test stacks
echo "Fetching test stac repo into: $STACK_REPO_BASE_DIR"
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
