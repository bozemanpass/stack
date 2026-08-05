#!/usr/bin/env bash
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

require_commands kind

select_test_target "$@"

stack="test-database-stack"
spec_file=${stack}-spec.yml
deployment_dir=${stack}-deployment

setup_test_dir database-test-dir
# We must delete any instances of the test-container in the local registory
# otherwise we'll skip building it below
remove_local_images bozemanpass/test-database-client
remove_local_images bozemanpass/test-database-container
# Fetch the test stacks
echo "Fetching test stack repo into: $STACK_REPO_BASE_DIR"
$TEST_TARGET_STACK fetch repo github.com/bozemanpass/stack-test-stacks
$TEST_TARGET_STACK prepare --stack ${stack}
# Test basic stack deploy to k8s
test_deployment_dir=$STACK_TEST_DIR/${deployment_dir}
test_deployment_spec=$STACK_TEST_DIR/${spec_file}

$TEST_TARGET_STACK init --stack ${stack} --deploy-to k8s-kind --output $test_deployment_spec
# Check the file now exists
if [ ! -f "$test_deployment_spec" ]; then
    fail "deploy init test: FAILED - spec file not present"
fi
echo "deploy init test: passed"

# Switch to a full path for the data dir so it gets provisioned as a host bind mounted volume and preserved beyond cluster lifetime
sed -i "s|^\(\s*db-data:$\)$|\1 ${test_deployment_dir}/data/db-data|" $test_deployment_spec

stop_deployment_on_exit $test_deployment_dir
$TEST_TARGET_STACK deploy --spec-file $test_deployment_spec --deployment-dir $test_deployment_dir
# Check the deployment dir exists
if [ ! -d "$test_deployment_dir" ]; then
    fail "deploy create test: FAILED - deployment directory not present"
fi
echo "deploy create test: passed"

# Try to start the deployment
$TEST_TARGET_STACK manage --dir $test_deployment_dir start
wait_for_containers_started
# Check logs command works
wait_for_log_content "Database test client: test complete"
log_output_1=$( $TEST_TARGET_STACK manage --dir $test_deployment_dir logs )
if [[ "$log_output_1" == *"Database test client: test data does not exist"* ]]; then
    echo "Create database content test: passed"
else
    fail "Create database content test: FAILED"
fi

# Stop then start again and check the volume was preserved
$TEST_TARGET_STACK manage --dir $test_deployment_dir stop
# Sleep a bit just in case
sleep 20
$TEST_TARGET_STACK manage --dir $test_deployment_dir start
wait_for_containers_started
wait_for_log_content "Database test client: test complete"

log_output_2=$( $TEST_TARGET_STACK manage --dir $test_deployment_dir logs )
if [[ "$log_output_2" == *"Database test client: test data already exists"* ]]; then
    echo "Retain database content test: passed"
else
    fail "Retain database content test: FAILED"
fi

# The registered teardown stops the deployment and deletes its volumes.
echo "Test passed"
