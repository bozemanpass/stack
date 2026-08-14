#!/usr/bin/env bash
#
# Check that the k8s pod placement controls -- node affinity and taint
# toleration, see docs/k8s-deployment-enhancements.md -- actually place the
# stack's pod where they say they will.
#
# This is deliberately a test of its own rather than something bolted onto the
# main deploy test: placement control is a niche k8s feature, and testing it
# needs a cluster built specially for it, with labelled and tainted worker nodes
# that no other test wants.
#
# Kind-only, and not because of a shortcut: the test has to construct a
# multi-node cluster with labels and taints of its choosing, and kind is the only
# target where the test owns the cluster.  It still goes through
# select_deploy_target so the init plumbing stays shared with the other tests.
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

require_commands kind kubectl

if [ -n "$STACK_TEST_TARGET" ] && [ "$STACK_TEST_TARGET" != "kind" ]; then
    fail "Error: this test builds its own multi-node cluster and runs on kind only, not $STACK_TEST_TARGET"
fi
export STACK_TEST_TARGET=kind

STACK_NAME="test"

echo "Running k8s deployment control test"
select_test_target "$@"
select_deploy_target
setup_test_dir k8s-deployment-control-test-dir

$TEST_TARGET_STACK fetch repo github.com/bozemanpass/stack-test-stacks
$TEST_TARGET_STACK prepare --stack $STACK_NAME

# Deployment artifacts live outside the repo base dir, so the deployment's copy
# of the stack files is not seen when resolving stacks by name.
test_deployment_dir=$STACK_TEST_DIR/test-deployment-dir
test_deployment_spec=$STACK_TEST_DIR/test-deployment-spec.yml

$TEST_TARGET_STACK init \
    --stack $STACK_NAME \
    --output $test_deployment_spec \
    $TEST_INIT_ARGS

if [ ! -f "$test_deployment_spec" ]; then
    fail "deploy init test: FAILED - spec file not present"
fi
echo "deploy init test: passed"

stop_deployment_on_exit $test_deployment_dir
$TEST_TARGET_STACK deploy --spec-file $test_deployment_spec --deployment-dir $test_deployment_dir
if [ ! -d "$test_deployment_dir" ]; then
    fail "deploy create test: FAILED - deployment directory not present"
fi
echo "deploy create test: passed"

# `deploy` has written a single-node kind config, carrying the port mappings and
# the bind mounts for the deployment's volumes.  Append to it rather than
# replacing it: the mounts belong to the control-plane node entry, and a
# hand-written replacement would silently drop them, leaving a deployment whose
# pod has nowhere to mount /data.
#
# Three workers are added, labelled nodetype=a/b/c, with worker3 additionally
# tainted nodeavoid=c.  A top-level kubeadm patch turns the scheduler's log level
# up, so that a placement failure leaves something to read:
#   kubectl -n kube-system logs kube-scheduler-<cluster>-control-plane
cat << EOF >> ${test_deployment_dir}/kind-config.yml
- role: worker
  labels:
    nodetype: a
- role: worker
  labels:
    nodetype: b
- role: worker
  labels:
    nodetype: c
  kubeadmConfigPatches:
  - |
    kind: JoinConfiguration
    nodeRegistration:
      taints:
        - key: "nodeavoid"
          value: "c"
          effect: "NoSchedule"
kubeadmConfigPatches:
- |
  kind: ClusterConfiguration
  scheduler:
    extraArgs:
      v: "3"
EOF

# The cluster that produces, with the labels this test placed (trailing column
# elided -- each node also carries the usual beta.kubernetes.io/* and
# kubernetes.io/* labels):
#
# $ kubectl get nodes --show-labels=true
# NAME                                   STATUS   ROLES           AGE   VERSION   LABELS
# stack-ffe2210246715ae3-control-plane   Ready    control-plane   91s   v1.34.0   ...,ingress-ready=true,...
# stack-ffe2210246715ae3-worker          Ready    <none>          82s   v1.34.0   ...,nodetype=a
# stack-ffe2210246715ae3-worker2         Ready    <none>          82s   v1.34.0   ...,nodetype=b
# stack-ffe2210246715ae3-worker3         Ready    <none>          82s   v1.34.0   ...,nodetype=c
#
# and with these taints:
#
# $ kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints --no-headers
# stack-ffe2210246715ae3-control-plane   [map[effect:NoSchedule key:node-role.kubernetes.io/control-plane]]
# stack-ffe2210246715ae3-worker          <none>
# stack-ffe2210246715ae3-worker2         <none>
# stack-ffe2210246715ae3-worker3         [map[effect:NoSchedule key:nodeavoid value:c]]

# Require the pod to land on a node labelled nodetype=c, and let it tolerate the
# taint that keeps everything else off that node.  Between them, exactly one node
# is a legal placement -- so the check below distinguishes the controls working
# from the scheduler having picked that node anyway.
cat << EOF >> ${test_deployment_dir}/spec.yml
node-affinities:
  - label: nodetype
    value: c
node-tolerations:
  - key: nodeavoid
    value: c
EOF

# The deployment id is the kind cluster name, the namespace, and the pod's "app"
# label, so the kubectl calls below need only this one value.
deployment_id=$( grep '^cluster-id:' ${test_deployment_dir}/deployment.yml | cut -d ' ' -f 2 )

$TEST_TARGET_STACK manage --dir $test_deployment_dir start
wait_for_running 1 $TEST_START_CHECK_LIMIT
wait_for_log_content "filesystem is fresh"
echo "deployment of pod test: passed"

deployment_node=$( kubectl --context kind-${deployment_id} -n ${deployment_id} \
    get pods -l app=${deployment_id} -o=jsonpath='{.items..spec.nodeName}' )
expected_node=${deployment_id}-worker3
echo "Stack pod deployed to node: ${deployment_node}"
if [ "${deployment_node}" != "${expected_node}" ]; then
    kubectl --context kind-${deployment_id} get nodes --show-labels=true || true
    fail "pod placement test: FAILED - pod on node ${deployment_node}, expected ${expected_node}"
fi
echo "pod placement test: passed"

echo "Test passed"
