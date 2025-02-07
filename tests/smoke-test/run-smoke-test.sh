#!/usr/bin/env bash
set -e
if [ -n "$BPI_SCRIPT_DEBUG" ]; then
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
export BPI_REPO_BASE_DIR=~/stack-test/repo-base-dir
echo "Testing this package: $TEST_TARGET_SO"
echo "Test version command"
reported_version_string=$( $TEST_TARGET_SO version )
echo "Version reported is: ${reported_version_string}"
echo "Cloning repositories into: $BPI_REPO_BASE_DIR"
rm -rf $BPI_REPO_BASE_DIR
mkdir -p $BPI_REPO_BASE_DIR
# Pull an example small public repo to test we can pull a repo
$TEST_TARGET_SO setup-repositories --include cerc-io/registry-sdk
# Test pulling a stack
$TEST_TARGET_SO --stack test setup-repositories
# Test building the a stack container
$TEST_TARGET_SO --stack test build-containers
# Build one example containers
$TEST_TARGET_SO build-containers --include bpi/builder-js
echo "Images in the local registry:"
docker image ls -a
# Deploy the test container
$TEST_TARGET_SO --stack test deploy up
# TODO: test that we can use the deployed container somehow
# Clean up
$TEST_TARGET_SO --stack test deploy down
# Run same test but not using the stack definition
# Test building the a stack container
$TEST_TARGET_SO build-containers --include bpi/test-container
echo "Test passed"
