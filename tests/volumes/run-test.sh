#!/usr/bin/env bash
#
# Check that a volume mapped to a chosen directory in the spec surfaces that
# directory's pre-existing contents inside the container.
#
# The default mapping (./data/<name> under the deployment directory) is covered
# indirectly by tests/database, which proves data written through it survives a
# stop/start.  What nothing else covers is the other direction: data that exists
# on the host *before* the deployment does, reaching the container through a
# path the spec chose -- the "consume an external dataset" case described in
# docs/volumes.md.
#
# The test stack's container reports, for each of its two data volumes, whether
# it found an `exists` file (logging the file's contents) or created one.  So:
# seed a directory outside the deployment directory with an `exists` file
# holding a sentinel, point the spec's `test-data-bind` volume at it, and the
# sentinel appearing in the logs is data that could only have come from the
# seeded directory.  The unmapped `test-data-auto` volume must report fresh in
# the same run, without which the sentinel assertion could pass vacuously (a
# container looking at its own filesystem would report "old" too, on any start
# after the first).
#
# The same spec mechanism lands completely differently per target, which is why
# this runs on three of them:
#
#   compose   a bind mount of the seeded directory
#   kind      the directory bind-mounted into the cluster node at creation,
#             with a hostPath PersistentVolume inside the node pointing at the
#             mount
#   remote    the seeded directory is on the cluster's node, so the spec entry
#             uses the mapping form -- path plus affinity (docs/volumes.md
#             "Placing the pod where the data is") -- and what is generated is
#             a `local` PersistentVolume carrying the node affinity.  This is
#             the only target where that code path runs for real, so it is the
#             leg that actually tests it.  Seeding and asserting on the node's
#             filesystem happens over SSH, via the command the cluster harness
#             publishes as STACK_TEST_NODE_SSH_COMMAND (tests/k3s-deploy);
#             without it the remote target is refused.
#
# remote-compose is refused: it deploys with the ordinary compose deployer, so
# the compose leg already covers its volume behavior.
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

select_test_target "$@"
select_deploy_target
case "$TEST_TARGET_ENV" in
    compose|kind) ;;
    remote)
        if [ -z "$STACK_TEST_NODE_SSH_COMMAND" ]; then
            fail "Error: the volumes test on the remote target requires STACK_TEST_NODE_SSH_COMMAND (see tests/k3s-deploy/cluster.sh)"
        fi
        ;;
    *)
        fail "Error: the volumes test does not support the $TEST_TARGET_ENV target (the compose leg covers its volume behavior)"
        ;;
esac

# Run a command on the k8s node, for the remote leg.  Deliberately unquoted:
# the published value is a whole ssh command line.
node_exec () {
    $STACK_TEST_NODE_SSH_COMMAND "$@"
}

stack="test"
spec_file=${stack}-spec.yml
deployment_dir=${stack}-deployment

setup_test_dir volumes-test-dir
# We must delete any instances of the test-container in the local registry
# otherwise we'll skip building it below
remove_local_images bozemanpass/test-container
echo "Fetching test stack repo into: $STACK_REPO_BASE_DIR"
$TEST_TARGET_STACK fetch repo github.com/bozemanpass/stack-test-stacks
$TEST_TARGET_STACK prepare --stack ${stack}

test_deployment_dir=$STACK_TEST_DIR/${deployment_dir}
test_deployment_spec=$STACK_TEST_DIR/${spec_file}

# The pre-existing dataset: a directory outside the deployment directory,
# holding the `exists` file the container looks for, with contents no container
# start could have written.  On the local targets it lives under the test
# directory; on the remote target it is a directory on the cluster's node.
sentinel="VOLUMES-TEST-SENTINEL-$$"
if [ "$TEST_TARGET_ENV" == "remote" ]; then
    external_data_dir=/srv/stack-volumes-test
    node_exec "sudo rm -rf $external_data_dir && sudo mkdir -p $external_data_dir && echo $sentinel | sudo tee $external_data_dir/exists > /dev/null"
    remove_node_data_dir () {
        node_exec "sudo rm -rf $external_data_dir"
    }
    TEST_EXTRA_CLEANUP=remove_node_data_dir
else
    external_data_dir=$STACK_TEST_DIR/external-data
    mkdir -p $external_data_dir
    echo "$sentinel" > $external_data_dir/exists
fi

$TEST_TARGET_STACK init --stack ${stack} $TEST_INIT_ARGS --output $test_deployment_spec
# Point the test-data-bind volume at the seeded directory.  test-data-auto
# keeps its default, as the control.  On the local targets that replaces the
# ./data/test-data-bind default with a bare path; on the remote target, where
# init leaves the volume unmapped, it becomes the mapping form -- the path on
# the node plus an affinity naming the node -- so that the leg exercises the
# `local` PersistentVolume path end to end.
if [ "$TEST_TARGET_ENV" == "remote" ]; then
    node_name=$( node_exec "sudo kubectl get nodes -o jsonpath='{.items[0].metadata.name}'" )
    if [ -z "$node_name" ]; then
        fail "Error: could not determine the cluster's node name"
    fi
    sed -i "s|^  test-data-bind:.*|  test-data-bind:\n    path: ${external_data_dir}\n    affinity:\n      label: kubernetes.io/hostname\n      value: ${node_name}|" $test_deployment_spec
else
    sed -i "s|test-data-bind: ./data/test-data-bind|test-data-bind: ${external_data_dir}|" $test_deployment_spec
fi
assert_file_contains $test_deployment_spec "${external_data_dir}" "spec volume mapping edit"

stop_deployment_on_exit $test_deployment_dir
$TEST_TARGET_STACK deploy --spec-file $test_deployment_spec --deployment-dir $test_deployment_dir

push_images_if_needed $test_deployment_dir

$TEST_TARGET_STACK manage --dir $test_deployment_dir start
wait_for_containers_started
# The container logs its volume report at startup and then blocks serving HTTP,
# so once the report's last line ("/data2 filesystem is old|fresh") is present
# the lines asserted on below are all there and stable.
wait_for_log_content "/data2 filesystem is"
log_file=$STACK_TEST_DIR/logs.txt
$TEST_TARGET_STACK manage --dir $test_deployment_dir logs > $log_file

# The volume is a real mount, not a directory on the container's own filesystem.
assert_file_contains $log_file "/data: MOUNTED" "volume mounted test"
# The sentinel could only have come from the seeded host directory.
assert_file_contains $log_file "/data filesystem is old, created: ${sentinel}" "external data visible test"
# The control: a first start on the volume that was left at its default.
assert_file_contains $log_file "/data2 filesystem is fresh" "unmapped volume fresh test"

# The other direction: something the container writes is visible at the chosen
# path outside it.  On the local targets, the `exists` file the container just
# wrote into the default-mapped volume appears in the deployment's data
# directory; on the remote target, where only the mapped volume has a knowable
# node path, a file is written into it and read back off the node.
if [ "$TEST_TARGET_ENV" == "remote" ]; then
    deployment_exec test "echo ${sentinel}-written > /data/write-back"
    written=$( node_exec "cat $external_data_dir/write-back" )
    if [ "$written" == "${sentinel}-written" ]; then
        echo "volume write-back test: PASSED"
    else
        fail "volume write-back test: FAILED - $external_data_dir/write-back on the node held '$written'"
    fi
elif [ -f "$test_deployment_dir/data/test-data-auto/exists" ]; then
    echo "volume write-back test: PASSED"
else
    fail "volume write-back test: FAILED - $test_deployment_dir/data/test-data-auto/exists not present on the host"
fi

# The registered teardown stops the deployment and deletes its volumes.
echo "Test passed"
