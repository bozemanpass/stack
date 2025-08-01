#!/usr/bin/env bash
set -e
if [ -n "$STACK_SCRIPT_DEBUG" ]; then
    set -x
    # Dump environment variables for debugging
    echo "Environment variables:"
    env
fi

if [ "$1" == "from-path" ]; then
    TEST_TARGET_SO="stack"
else
    TEST_TARGET_SO=$( ls -t1 ./package/stack* | head -1 )
fi

export STACK_USE_BUILTIN_STACK=true

stack="test-database"
spec_file=${stack}-spec.yml
deployment_dir=${stack}-deployment

# Helper functions: TODO move into a separate file
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
    delete_cluster_exit
}

wait_for_test_complete () {
    for i in {1..50}
    do

        local log_output=$( $TEST_TARGET_SO manage --dir $test_deployment_dir logs )

    if [[ "${log_output}" == *"Database test client: test complete"* ]]; then
            # if ready, return
            return
        else
            # if not ready, wait
            sleep 5
        fi
    done
    # Timed out, error exit
    echo "waiting for test complete: FAILED"
    delete_cluster_exit
}


delete_cluster_exit () {
    $TEST_TARGET_SO manage --dir $test_deployment_dir stop --delete-volumes
    exit 1
}

# Set a non-default repo dir
export STACK_REPO_BASE_DIR=~/stack-test/repo-base-dir
echo "Testing this package: $TEST_TARGET_SO"
echo "Test version command"
reported_version_string=$( $TEST_TARGET_SO version )
echo "Version reported is: ${reported_version_string}"
echo "Cloning repositories into: $STACK_REPO_BASE_DIR"
rm -rf $STACK_REPO_BASE_DIR
mkdir -p $STACK_REPO_BASE_DIR
$TEST_TARGET_SO fetch repositories --stack ${stack}
$TEST_TARGET_SO build containers --stack ${stack}
# Test basic stack deploy to k8s
test_deployment_dir=$STACK_REPO_BASE_DIR/${deployment_dir}
test_deployment_spec=$STACK_REPO_BASE_DIR/${spec_file}

$TEST_TARGET_SO --stack ${stack} deploy --deploy-to k8s-kind init --output $test_deployment_spec
# Check the file now exists
if [ ! -f "$test_deployment_spec" ]; then
    echo "deploy init test: spec file not present"
    echo "deploy init test: FAILED"
    exit 1
fi
echo "deploy init test: passed"

# Switch to a full path for the data dir so it gets provisioned as a host bind mounted volume and preserved beyond cluster lifetime
sed -i "s|^\(\s*db-data:$\)$|\1 ${test_deployment_dir}/data/db-data|" $test_deployment_spec

$TEST_TARGET_SO --stack ${stack} deploy --spec-file $test_deployment_spec --deployment-dir $test_deployment_dir
# Check the deployment dir exists
if [ ! -d "$test_deployment_dir" ]; then
    echo "deploy create test: deployment directory not present"
    echo "deploy create test: FAILED"
    exit 1
fi
echo "deploy create test: passed"

# Try to start the deployment
$TEST_TARGET_SO manage --dir $test_deployment_dir start
wait_for_pods_started
# Check logs command works
wait_for_test_complete
log_output_1=$( $TEST_TARGET_SO manage --dir $test_deployment_dir logs )
if [[ "$log_output_1" == *"Database test client: test data does not exist"* ]]; then
    echo "Create database content test: passed"
else
    echo "Create database content test: FAILED"
    delete_cluster_exit
fi

# Stop then start again and check the volume was preserved
$TEST_TARGET_SO manage --dir $test_deployment_dir stop
# Sleep a bit just in case
sleep 20
$TEST_TARGET_SO manage --dir $test_deployment_dir start
wait_for_pods_started
wait_for_test_complete

log_output_2=$( $TEST_TARGET_SO manage --dir $test_deployment_dir logs )
if [[ "$log_output_2" == *"Database test client: test data already exists"* ]]; then
    echo "Retain database content test: passed"
else
    echo "Retain database content test: FAILED"
    delete_cluster_exit
fi

# Stop and clean up
$TEST_TARGET_SO manage --dir $test_deployment_dir stop --delete-volumes
echo "Test passed"
