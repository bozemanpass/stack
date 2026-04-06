#!/usr/bin/env bash
set -e
if [ -n "$STACK_SCRIPT_DEBUG" ]; then
    set -x
    # Dump environment variables for debugging
    echo "Environment variables:"
    env
fi

if ! command -v kind &> /dev/null; then
    echo "Error: 'kind' is not installed or not available on the PATH"
    exit 1
fi

if [ "$1" == "from-path" ]; then
    TEST_TARGET_STACK="stack"
else
    TEST_TARGET_STACK=$( ls -t1 ./package/stack* | head -1 )
fi

stack="test-database-stack"
spec_file=${stack}-spec.yml
deployment_dir=${stack}-deployment

# Helper functions: TODO move into a separate file
wait_for_pods_started () {
    for i in {1..50}
    do
        local ps_output=$( $TEST_TARGET_STACK manage --dir $test_deployment_dir ps )

        if [[ "$ps_output" == *"id:"* ]]; then
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

        local log_output=$( $TEST_TARGET_STACK manage --dir $test_deployment_dir logs )

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
    $TEST_TARGET_STACK manage --dir $test_deployment_dir stop --delete-volumes
    exit 1
}

# We make a directory within which our test will create files
STACK_TEST_DIR=~/stack-test/database-test-dir
# Set a non-default repo dir
export STACK_REPO_BASE_DIR=${STACK_TEST_DIR}/repo-base-dir
echo "Testing this package: $TEST_TARGET_STACK"
echo "Test version command"
reported_version_string=$( $TEST_TARGET_STACK version )
echo "Version reported is: ${reported_version_string}"
echo "Using test directory: $STACK_TEST_DIR"
rm -rf $STACK_TEST_DIR
mkdir -p $STACK_TEST_DIR
mkdir -p $STACK_REPO_BASE_DIR
# We must delete any instances of the test-container in the local registory
# otherwise we'll skip building it below
existing_test_images=$(docker image ls -q --filter=reference=bozemanpass/test-database-client | uniq)
if [ -n "$existing_test_images" ]; then
  docker image rm -f ${existing_test_images}
fi
existing_test_images=$(docker image ls -q --filter=reference=bozemanpass/test-database-container | uniq)
if [ -n "$existing_test_images" ]; then
  docker image rm -f ${existing_test_images}
fi
# Fetch the test stacks
echo "Fetching test stack repo into: $STACK_REPO_BASE_DIR"
$TEST_TARGET_STACK fetch repo github.com/bozemanpass/stack-test-stacks
$TEST_TARGET_STACK prepare --stack ${stack}
# Test basic stack deploy to k8s
test_deployment_dir=$STACK_REPO_BASE_DIR/${deployment_dir}
test_deployment_spec=$STACK_REPO_BASE_DIR/${spec_file}

$TEST_TARGET_STACK init --stack ${stack} --deploy-to k8s-kind --output $test_deployment_spec
# Check the file now exists
if [ ! -f "$test_deployment_spec" ]; then
    echo "deploy init test: spec file not present"
    echo "deploy init test: FAILED"
    exit 1
fi
echo "deploy init test: passed"

# Switch to a full path for the data dir so it gets provisioned as a host bind mounted volume and preserved beyond cluster lifetime
sed -i "s|^\(\s*db-data:$\)$|\1 ${test_deployment_dir}/data/db-data|" $test_deployment_spec

$TEST_TARGET_STACK deploy --spec-file $test_deployment_spec --deployment-dir $test_deployment_dir
# Check the deployment dir exists
if [ ! -d "$test_deployment_dir" ]; then
    echo "deploy create test: deployment directory not present"
    echo "deploy create test: FAILED"
    exit 1
fi
echo "deploy create test: passed"

# Try to start the deployment
$TEST_TARGET_STACK manage --dir $test_deployment_dir start
wait_for_pods_started
# Check logs command works
wait_for_test_complete
log_output_1=$( $TEST_TARGET_STACK manage --dir $test_deployment_dir logs )
if [[ "$log_output_1" == *"Database test client: test data does not exist"* ]]; then
    echo "Create database content test: passed"
else
    echo "Create database content test: FAILED"
    delete_cluster_exit
fi

# Stop then start again and check the volume was preserved
$TEST_TARGET_STACK manage --dir $test_deployment_dir stop
# Sleep a bit just in case
sleep 20
$TEST_TARGET_STACK manage --dir $test_deployment_dir start
wait_for_pods_started
wait_for_test_complete

log_output_2=$( $TEST_TARGET_STACK manage --dir $test_deployment_dir logs )
if [[ "$log_output_2" == *"Database test client: test data already exists"* ]]; then
    echo "Retain database content test: passed"
else
    echo "Retain database content test: FAILED"
    delete_cluster_exit
fi

# Stop and clean up
$TEST_TARGET_STACK manage --dir $test_deployment_dir stop --delete-volumes
echo "Test passed"
