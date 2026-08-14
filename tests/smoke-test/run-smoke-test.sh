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
# The test stack ships deploy hooks in its deploy/commands.py, and `init` calls the
# first of them: it adds a config variable to the spec being generated.
assert_file_contains $test_deployment_spec "test-variable-1: test-value-1" "deploy init hook"
$TEST_TARGET_STACK deploy --spec-file $test_deployment_spec --deployment-dir $test_deployment_dir
# ...and `deploy` calls the second, which writes a known file into the deployment
# directory.  Assert on the side effects rather than on the commands exiting 0: a
# missed hook lookup is silent, which is exactly how these went uncalled for months
# without a test noticing (bozemanpass/stack#232).
if [ ! -f "$test_deployment_dir/create-file" ]; then
    fail "deploy create hook: FAILED - create-file not written"
fi
assert_file_contains $test_deployment_dir/create-file "create-command-output-data" "deploy create hook"
# Up
$TEST_TARGET_STACK manage --dir $test_deployment_dir start
# Down
$TEST_TARGET_STACK manage --dir $test_deployment_dir stop
# Run same test but not using the stack definition
# Test building the a stack container
$TEST_TARGET_STACK --debug --verbose build containers --stack test --include bozemanpass/test-container
echo "Test passed"
