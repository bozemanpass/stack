#!/usr/bin/env bash
#
# Check that the `runtime-class` spec key (docs/k8s-deployment-enhancements.md)
# really puts the service that asked for it inside a VM, and leaves the one
# that did not alone.
#
# The evidence is the kernel version. A container shares the host's kernel and
# cannot do otherwise; a pod on the kata RuntimeClass boots a kernel of its own.
# So a service reporting a kernel that is not the node's is a service that is
# not a container on that node -- which is the whole claim the feature makes.
#
# Both directions are asserted, and the second is not decoration:
#
#   * the sandboxed service reports a kernel that is not the node's
#   * the ordinary service in the same deployment reports one that is
#
# Without the control, "reports a different kernel" would also be satisfied by a
# comparison that was broken in some way that made every answer differ. It is
# also the assertion that the per-service form did what it says: a deployment
# where naming one service put every pod in a VM would be a worse feature than
# the one documented, and would pass a test that only looked at the kata pod.
#
# Two stacks in one deployment, rather than two deployments, for exactly that
# reason: the two pods are then on the same node at the same time under the same
# spec, so the only thing that differs between them is the spec key under test.
# The sandboxed one is the static content stack -- an unremarkable nginx with no
# volumes -- because what a guest VM does with a PVC is a separate question from
# whether it is a guest VM at all, and the test stack (three volumes) is the
# better control for the same reason.
#
# Remote-only, and not out of laziness: kata needs a runtime installed on the
# nodes and a host that allows nested virtualization, which the cluster harness
# provisions (tests/k3s-deploy/cluster.sh, STACK_K3S_KATA) and a kind cluster
# has no way to offer. The generated-manifest side of the feature -- which pods
# name the class, and which do not -- is covered without a cluster at all, in
# tests/unit/test_k8s_runtime_class.py.
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

echo "Running kata runtime class test"
select_test_target "$@"
select_deploy_target

if [ "$TEST_TARGET_ENV" != "remote" ]; then
    fail "Error: this test needs a cluster with a kata runtime and runs on the remote target only, not $TEST_TARGET_ENV"
fi
if [ -z "$STACK_TEST_KATA_RUNTIME_CLASS" ]; then
    fail "Error: this test requires STACK_TEST_KATA_RUNTIME_CLASS (provision with STACK_K3S_KATA=true; see tests/k3s-deploy/cluster.sh)"
fi
if [ -z "$STACK_TEST_NODE_SSH_COMMAND" ]; then
    fail "Error: this test requires STACK_TEST_NODE_SSH_COMMAND to read the node's own kernel (see tests/k3s-deploy/cluster.sh)"
fi

# Run a command on the k8s node.  Deliberately unquoted: the published value is
# a whole ssh command line.
node_exec () {
    $STACK_TEST_NODE_SSH_COMMAND "$@"
}

# The kernel one of the deployment's services sees.  Trimmed of whitespace so
# that the comparisons below are between the versions and nothing else.
kernel_in_service () {
    deployment_exec "$1" "uname -r" | tr -d '[:space:]'
}

sandboxed_stack="test-static-content"
sandboxed_service="static-content"
ordinary_stack="test"
ordinary_service="test"

setup_test_dir kata-test-dir

$TEST_TARGET_STACK fetch repo github.com/bozemanpass/stack-test-stacks
$TEST_TARGET_STACK prepare --stack ${ordinary_stack}
$TEST_TARGET_STACK prepare --stack ${sandboxed_stack}

test_deployment_dir=$STACK_TEST_DIR/kata-deployment
sandboxed_spec=$STACK_TEST_DIR/${sandboxed_stack}-spec.yml
ordinary_spec=$STACK_TEST_DIR/${ordinary_stack}-spec.yml

$TEST_TARGET_STACK init --stack ${sandboxed_stack} --output $sandboxed_spec $TEST_INIT_ARGS
$TEST_TARGET_STACK init --stack ${ordinary_stack} --output $ordinary_spec $TEST_INIT_ARGS

# The spec key under test, written the way the documentation says to write it:
# named for one service, in the spec of the stack that service belongs to.  No
# `default`, so the other stack's service is untouched -- which is what the
# control below asserts from the inside.
cat << EOF >> $sandboxed_spec
runtime-class:
  services:
    ${sandboxed_service}: ${STACK_TEST_KATA_RUNTIME_CLASS}
EOF

stop_deployment_on_exit $test_deployment_dir
$TEST_TARGET_STACK deploy --spec-file $sandboxed_spec --spec-file $ordinary_spec \
    --deployment-dir $test_deployment_dir
if [ ! -d "$test_deployment_dir" ]; then
    fail "deploy create test: FAILED - deployment directory not present"
fi
assert_file_contains $test_deployment_dir/spec.yml "${STACK_TEST_KATA_RUNTIME_CLASS}" "runtime class in merged spec test"

push_images_if_needed $test_deployment_dir

$TEST_TARGET_STACK manage --dir $test_deployment_dir start
# A sandboxed pod boots a kernel and a rootfs before its container starts, so it
# reaches "running" later than an ordinary one does.
wait_for_running 2 $TEST_START_CHECK_LIMIT
echo "deployment of sandboxed and ordinary pods test: passed"

node_kernel=$( node_exec "uname -r" | tr -d '[:space:]' )
if [ -z "$node_kernel" ]; then
    fail "kata isolation test: FAILED - could not read the node's kernel version"
fi
echo "The cluster node's own kernel is ${node_kernel}"

# The control, asserted first: without it a differing kernel below says nothing,
# and this is also what says the pod that asked for nothing got nothing.
ordinary_kernel=$( kernel_in_service ${ordinary_service} )
if [ "$ordinary_kernel" != "$node_kernel" ]; then
    fail "unsandboxed pod control test: FAILED - ${ordinary_service} reported kernel '${ordinary_kernel}', but the node runs '${node_kernel}' - an ordinary container shares the node's kernel, so this comparison is not measuring what it should"
fi
echo "unsandboxed pod control test: passed"

sandboxed_kernel=$( kernel_in_service ${sandboxed_service} )
if [ -z "$sandboxed_kernel" ]; then
    fail "kata isolation test: FAILED - could not read the kernel version in ${sandboxed_service}"
fi
if [ "$sandboxed_kernel" == "$node_kernel" ]; then
    fail "kata isolation test: FAILED - ${sandboxed_service} reported the node's own kernel '${sandboxed_kernel}', so it is not running in a VM"
fi
echo "kata isolation test: passed - ${sandboxed_service} runs kernel ${sandboxed_kernel}, not the node's ${node_kernel}"

echo "Test passed"
