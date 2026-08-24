#!/usr/bin/env bash
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

# Basic simple test of stack functionality
echo "Running stack smoke test"
select_test_target "$@"
setup_test_dir smoke-test-dir
# We must delete any instances of the test-container in the local registory
# otherwise we'll skip building it below
remove_local_images bozemanpass/test-container
# First, the same stack from a working checkout the tool did not clone -- a developer
# tree, or a CI actions/checkout.  This phase must stay ahead of the fetch below: once
# the repo is under STACK_REPO_BASE_DIR the recipe resolves from there and the phase
# tests nothing (bozemanpass/stack#297).
checkout_dir=$STACK_TEST_DIR/checkout
git clone https://github.com/bozemanpass/stack-test-stacks $checkout_dir
# A path, not a name: a name is only resolvable through the repo base dir, so the path
# form is the only way to reach a stack that was never cloned.
$TEST_TARGET_STACK prepare --stack $checkout_dir/stack-files/stacks/test-stack
if ! docker image inspect bozemanpass/test-container:stack > /dev/null 2>&1; then
    fail "prepare from local checkout: FAILED - image not built"
fi
# The stack's colocated container recipe has to come from the checkout itself.  Assert
# that it was not instead obtained by quietly cloning the repo: a build that reaches the
# recipe by way of the repo base dir is the bug, whether or not an image comes out of it.
if [ -d "$STACK_REPO_BASE_DIR/github.com/bozemanpass/stack-test-stacks" ]; then
    fail "prepare from local checkout: FAILED - stack repo was cloned into $STACK_REPO_BASE_DIR"
fi
echo "prepare from local checkout: PASSED"
# The checkout and the clone below are the same commit, so they yield the same image
# identity: leaving this image in place would make the build that follows a no-op.
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
# Destroy: the signal that the deployment is finished.  On compose a stopped
# deployment and a destroyed one look much the same from outside, so what is
# asserted is the marker destroy leaves and the refusal that follows it -- a
# deployment directory whose objects are gone must not go on answering questions
# about them.
$TEST_TARGET_STACK manage --dir $test_deployment_dir destroy --yes
if [ ! -f "$test_deployment_dir/destroyed" ]; then
    fail "deploy destroy: FAILED - destroyed marker not written"
fi
if $TEST_TARGET_STACK manage --dir $test_deployment_dir status > /dev/null 2>&1; then
    fail "deploy destroy: FAILED - manage still operates on a destroyed deployment"
fi
echo "deploy destroy: PASSED"
# Run same test but not using the stack definition
# Test building the a stack container
$TEST_TARGET_STACK --debug --verbose build containers --stack test --include bozemanpass/test-container
echo "Test passed"
