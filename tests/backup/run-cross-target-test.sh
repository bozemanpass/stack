#!/usr/bin/env bash
# Check that a backup taken on one deployment target restores on the other, in
# both directions: Docker Compose to Kubernetes, and Kubernetes back to Docker
# Compose.
#
# The two targets run different backup engines -- restic in a mixed-in backup
# container on Docker, K8up on a cluster -- against the same restic repository
# format, under the same repository and snapshot names.  That sameness is the
# claim that lets an operator move a deployment between targets, and it is not
# covered by the backup test, whose deployments are all on one target: each
# engine there only ever reads what it wrote itself.  Here each engine restores
# a repository the *other* one wrote.
#
# Flow, one bucket and three deployments of the same stack:
#
#   A (compose)  write a payload -> back it up (restic)
#   B (k8s)      assert the payload absent -> `backup restore --from` A's
#                repository (K8up reading restic's) -> assert it present;
#                then append a payload of its own -> back it up (K8up)
#   C (compose)  assert both payloads absent -> `backup restore --from` B's
#                repository (restic reading K8up's) -> assert both present:
#                B's is the k8s-to-compose direction, and A's has crossed
#                targets twice
#
# The volume path only: `backup restore` fills volumes, and the streamed-dump
# path is deliberately recovered outside the tool with the bare restic CLI
# (see tests/database/run-backup-test.sh), which is target-independent by
# construction and already covered there.
#
# Both targets at once is what this test is, so it is remote-only three times
# over: the k8s side needs K8up, which a kind cluster does not have; the object
# store has to be reachable from the cluster and from the local daemon alike,
# which the compose target's usual in-deployment SeaweedFS is not; and the
# compose side is this machine, so "remote" here still needs a local Docker.
# It refuses any other STACK_TEST_TARGET rather than silently testing less,
# and still goes through select_deploy_target/select_backup_target for the
# remote plumbing; the compose side's arrangement is inherent to the test, so
# it lives here rather than in a target helper.
#
# Requires Docker, plus the remote-target settings (STACK_KUBE_CONFIG,
# STACK_IMAGE_REGISTRY, STACK_K8S_HOSTNAME -- tests/k3s-deploy sets them up)
# and the object store settings select_backup_target lists for remote.  Run
# from the repo root, either:
#   STACK_TEST_TARGET=remote ./tests/backup/run-cross-target-test.sh
#   STACK_TEST_TARGET=remote ./tests/backup/run-cross-target-test.sh from-path
#
# NOTE: this fetches the test stacks and the backup stack from GitHub, so the
# `test-backup-stack` additions in bozemanpass/stack-test-stacks and the
# bozemanpass/backup-stack repo must be pushed for this to run.
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

require_commands docker

if [ -n "$STACK_TEST_TARGET" ] && [ "$STACK_TEST_TARGET" != "remote" ]; then
    fail "Error: the cross-target backup test needs a real cluster and runs on remote only, not $STACK_TEST_TARGET"
fi
export STACK_TEST_TARGET=remote

select_test_target "$@"
select_deploy_target
select_backup_target

app_stack="test-backup-stack"
backup_stack="backup"

# The compose deployments start the stack's app and the mixed-in backup
# container; the k8s deployment starts the app alone, K8up being the cluster's.
compose_service_count=2
k8s_service_count=1

# The compose target's startup wait: the images are local, so the remote
# target's TEST_START_CHECK_LIMIT (sized for registry pulls) does not apply.
compose_check_limit=10

# The payload file is /data/payload.txt because the stack's backup-command
# annotation is a cat of that path, run at backup time -- a payload anywhere
# else would make every `backup now` here fail on its dump step.
payload_a="cross-backup-compose-$$"
payload_b="cross-backup-k8s-$$"

setup_test_dir cross-backup-test-dir

# Fetch and prepare the stacks: the app stack for all three deployments, and
# the backup stack for the compose ones, where it is the engine.  No object
# store stack: the store is the real one the remote settings name, which is
# what both targets can reach.
remove_local_images bozemanpass/backup
$TEST_TARGET_STACK fetch repo github.com/bozemanpass/stack-test-stacks
$TEST_TARGET_STACK fetch repo github.com/bozemanpass/backup-stack
$TEST_TARGET_STACK prepare --stack ${app_stack}
$TEST_TARGET_STACK prepare --stack ${backup_stack}

compose_app_spec=$STACK_TEST_DIR/${app_stack}-compose-spec.yml
compose_backup_spec=$STACK_TEST_DIR/${backup_stack}-spec.yml
k8s_app_spec=$STACK_TEST_DIR/${app_stack}-k8s-spec.yml
deployment_a_dir=$STACK_TEST_DIR/${app_stack}-deployment-compose-a
deployment_b_dir=$STACK_TEST_DIR/${app_stack}-deployment-k8s
deployment_c_dir=$STACK_TEST_DIR/${app_stack}-deployment-compose-c

# Two specs for one stack: the compose deployments take no target plumbing at
# all, and the k8s one takes the remote target's.  `init` defaults --kube-config
# from the ambient STACK_KUBE_CONFIG the cluster harness exports, and refuses it
# on a compose spec, so the variable has to be genuinely absent -- not empty --
# for the compose inits.
env -u STACK_KUBE_CONFIG $TEST_TARGET_STACK init --stack ${app_stack} --output "$compose_app_spec"
env -u STACK_KUBE_CONFIG $TEST_TARGET_STACK init --stack ${backup_stack} --output "$compose_backup_spec"
$TEST_TARGET_STACK init --stack ${app_stack} $TEST_INIT_ARGS --output "$k8s_app_spec"

compose_spec_args=(--spec-file "$compose_backup_spec" --spec-file "$compose_app_spec")

# Three deployments, torn down however the test ends: the helpers act on the
# current one (stop_deployment_on_exit), and each deployment it moves on from
# is added to this list for the extra cleanup to stop.
extra_deployment_dirs=()
stop_extra_deployments () {
    local dir
    for dir in "${extra_deployment_dirs[@]}"; do
        $TEST_TARGET_STACK manage --dir "$dir" stop --delete-volumes
    done
}
TEST_EXTRA_CLEANUP=stop_extra_deployments

# --- A (compose): write the payload and back it up ---------------------------

stop_deployment_on_exit "$deployment_a_dir"
$TEST_TARGET_STACK deploy "${compose_spec_args[@]}" --deployment-dir "$deployment_a_dir"
$TEST_TARGET_STACK manage --dir "$deployment_a_dir" start
wait_for_running $compose_service_count $compose_check_limit

deployment_exec app "echo ${payload_a} > /data/payload.txt"
echo "wrote payload to the compose deployment: ${payload_a}"

# The name of the repository this deployment's backups land in, which is all
# the other deployments are given of it.
deployment_a=$( grep "^cluster-id:" "$deployment_a_dir/deployment.yml" | awk '{print $2}' )
if [ -z "$deployment_a" ]; then
    fail "Compose backup test: FAILED - no cluster-id in the deployment"
fi

# The engine creates the repository on first use, so no readiness loop; a
# couple of attempts cover a transient hiccup (see tests/backup/run-test.sh).
backed_up=
for i in {1..3}; do
    if $TEST_TARGET_STACK manage --dir "$deployment_a_dir" backup now; then backed_up=1; break; fi
    echo "backup attempt ${i} failed, retrying"
    sleep 5
done
if [ -z "$backed_up" ]; then
    fail "Compose backup test: FAILED"
fi
echo "Compose backup test: passed (restic wrote ${deployment_a})"

# --- B (k8s): restore compose's backup, then take one of its own -------------

$TEST_TARGET_STACK deploy --spec-file "$k8s_app_spec" --deployment-dir "$deployment_b_dir"
extra_deployment_dirs+=("$deployment_a_dir")
stop_deployment_on_exit "$deployment_b_dir"
push_images_if_needed "$deployment_b_dir"
$TEST_TARGET_STACK manage --dir "$deployment_b_dir" start
wait_for_running $k8s_service_count $TEST_START_CHECK_LIMIT

# Fresh volumes, so the payload cannot be there yet -- only a restore that
# actually read the compose deployment's repository can put it there.
empty=$( deployment_exec app "cat /data/payload.txt" 2>/dev/null || true )
if [[ "$empty" == *"$payload_a"* ]]; then
    fail "Compose-to-k8s restore test: FAILED - the k8s deployment already had the payload before restoring"
fi

# K8up reading the repository restic wrote.  The app's second volume is
# excluded from backups, so its restore is expected to be skipped with a
# warning rather than fail the rest (see backup_restore in deploy_k8s.py).
$TEST_TARGET_STACK manage --dir "$deployment_b_dir" backup restore --from "$deployment_a"

restored=$( deployment_exec app "cat /data/payload.txt" || true )
if [[ "$restored" != *"$payload_a"* ]]; then
    fail "Compose-to-k8s restore test: FAILED (expected '${payload_a}', got '${restored}')"
fi
echo "Compose-to-k8s restore test: passed"

# Appended rather than written, so the file now carries both payloads and the
# compose one gets to cross targets a second time below.
deployment_exec app "echo ${payload_b} >> /data/payload.txt"
echo "appended payload to the k8s deployment: ${payload_b}"

deployment_b=$( grep "^cluster-id:" "$deployment_b_dir/deployment.yml" | awk '{print $2}' )
if [ -z "$deployment_b" ]; then
    fail "K8s backup test: FAILED - no cluster-id in the deployment"
fi

backed_up=
for i in {1..3}; do
    if $TEST_TARGET_STACK manage --dir "$deployment_b_dir" backup now; then backed_up=1; break; fi
    echo "backup attempt ${i} failed, retrying"
    sleep 5
done
if [ -z "$backed_up" ]; then
    fail "K8s backup test: FAILED"
fi
echo "K8s backup test: passed (K8up wrote ${deployment_b})"

# --- C (compose): restore the k8s deployment's backup ------------------------

$TEST_TARGET_STACK deploy "${compose_spec_args[@]}" --deployment-dir "$deployment_c_dir"
extra_deployment_dirs+=("$deployment_b_dir")
stop_deployment_on_exit "$deployment_c_dir"
$TEST_TARGET_STACK manage --dir "$deployment_c_dir" start
wait_for_running $compose_service_count $compose_check_limit

empty=$( deployment_exec app "cat /data/payload.txt" 2>/dev/null || true )
if [[ "$empty" == *"$payload_b"* ]]; then
    fail "K8s-to-compose restore test: FAILED - the new compose deployment already had the payload before restoring"
fi

# restic reading the repository K8up wrote.
$TEST_TARGET_STACK manage --dir "$deployment_c_dir" backup restore --from "$deployment_b"

restored=$( deployment_exec app "cat /data/payload.txt" || true )
if [[ "$restored" != *"$payload_b"* ]]; then
    fail "K8s-to-compose restore test: FAILED (expected '${payload_b}', got '${restored}')"
fi
echo "K8s-to-compose restore test: passed"

# The compose payload again, now that it has been through both engines: written
# by restic, restored by K8up, backed up by K8up, restored by restic.
if [[ "$restored" != *"$payload_a"* ]]; then
    fail "Round trip test: FAILED (expected '${payload_a}' as well, got '${restored}')"
fi
echo "Round trip test: passed (the compose payload survived both directions)"

# The registered teardown stops all three deployments and deletes their volumes.
echo "Test passed"
