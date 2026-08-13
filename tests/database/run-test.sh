#!/usr/bin/env bash
#
# Check that data in a volume survives a stop/start of the deployment.
#
# The test stack is a database plus a client that, on each start, reports
# whether its test data is already there.  So a first start says "does not
# exist" and a second start must say "already exists".
#
# Runs against any of the three deployment targets (see select_deploy_target in
# tests/lib/common.sh); STACK_TEST_TARGET picks which:
#
#   STACK_TEST_TARGET=compose ./tests/database/run-test.sh   # the default
#   STACK_TEST_TARGET=kind    ./tests/database/run-test.sh
#   STACK_TEST_TARGET=remote  ./tests/database/run-test.sh   # see tests/k3s-deploy
#
# Worth running on all three because the thing under test -- where the bytes
# actually live -- is implemented completely differently on each: a volume
# managed by docker, a host directory mounted into a kind node, and a PVC from
# the cluster's default storage class.
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

select_test_target "$@"
select_deploy_target

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

test_deployment_dir=$STACK_TEST_DIR/${deployment_dir}
test_deployment_spec=$STACK_TEST_DIR/${spec_file}

$TEST_TARGET_STACK init --stack ${stack} $TEST_INIT_ARGS --output $test_deployment_spec
# Check the file now exists
if [ ! -f "$test_deployment_spec" ]; then
    fail "deploy init test: FAILED - spec file not present"
fi
echo "deploy init test: passed"

# On kind the data has to live on the host to survive the stop/start below,
# because stopping deletes the cluster.  The other two targets keep the default:
# compose gets a volume under the deployment directory, and a real cluster gets
# a PVC from the default storage class, which is the arrangement a production
# deployment would use and so the one worth exercising here.
if [ "$TEST_TARGET_ENV" == "kind" ]; then
    map_volume_to_host_path "$test_deployment_spec" db-data "${test_deployment_dir}/data/db-data"
fi

stop_deployment_on_exit $test_deployment_dir
$TEST_TARGET_STACK deploy --spec-file $test_deployment_spec --deployment-dir $test_deployment_dir
# Check the deployment dir exists
if [ ! -d "$test_deployment_dir" ]; then
    fail "deploy create test: FAILED - deployment directory not present"
fi
echo "deploy create test: passed"

push_images_if_needed $test_deployment_dir

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
