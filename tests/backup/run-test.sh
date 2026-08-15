#!/usr/bin/env bash
# End-to-end test of the backup/restore feature.
#
# Flow: deploy an app holding data in a volume -> write a known payload -> back it up ->
# wipe the data -> restore -> assert the payload came back (read through the app). Also
# asserts that the app's second volume, which the stack marks `@stack backup-exclude`, is
# not in the backup.
#
# Where the backup goes differs by target and is decided in select_backup_target: a real
# object store on a real cluster, and on the Docker target a SeaweedFS mixed into the
# deployment, since that target has no object store to hand.
#
# Every step goes through `stack manage ... backup`, so the same test runs against both
# backup engines: on the Docker target that is restic in the mixed-in backup stack, and
# on a real cluster it is K8up, which the cluster provides. The engines write the same
# restic repository format and the commands mean the same thing, which is most of what
# this test is checking.
#
# Requires Docker. Run from the repo root, either:
#   ./tests/backup/run-test.sh                # uses the built shiv package in ./package
#   ./tests/backup/run-test.sh from-path      # uses `stack` from PATH (dev mode)
#
# STACK_TEST_TARGET selects the target: compose (the default) or remote. There is no kind
# leg -- see select_backup_target in ../lib/common.sh. The remote target needs the object
# store settings that select_backup_target lists, in addition to the cluster settings
# select_deploy_target needs; tests/k3s-deploy/with-k3s-cluster.sh sets the latter up.
#
# NOTE: this fetches the test stacks and the backup stack from GitHub, so the
# `test-backup-stack` additions in bozemanpass/stack-test-stacks and the
# bozemanpass/backup-stack repo must be pushed for this to run.
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

require_commands docker

select_test_target "$@"
select_deploy_target
select_backup_target

app_stack="test-backup-stack"
backup_stack="backup"
s3_stack="test-s3-stack"
deployment_dir_name="${app_stack}-deployment"
app_spec="${app_stack}-spec.yml"
backup_spec="${backup_stack}-spec.yml"
s3_spec="${s3_stack}-spec.yml"

payload="backup-test-payload-$$"   # a value unique to this run

setup_test_dir backup-test-dir

# Fetch and prepare the stacks.
$TEST_TARGET_STACK fetch repo github.com/bozemanpass/stack-test-stacks
$TEST_TARGET_STACK prepare --stack ${app_stack}

test_deployment_dir=$STACK_TEST_DIR/${deployment_dir_name}
test_app_spec=$STACK_TEST_DIR/${app_spec}
test_backup_spec=$STACK_TEST_DIR/${backup_spec}
test_s3_spec=$STACK_TEST_DIR/${s3_spec}

$TEST_TARGET_STACK init --stack ${app_stack} --output "$test_app_spec" $TEST_INIT_ARGS

spec_args=(--spec-file "$test_app_spec")
if [ -n "$TEST_BACKUP_MIX_IN" ]; then
    # The Docker target has neither a backup operator nor an object store, so the
    # deployment carries both: the backup container is the engine, and SeaweedFS is
    # what it writes to. The restic password and store credentials reach the engine
    # from the ambient settings, not from here.
    # Force a rebuild of the backup image so the test exercises current sources.
    remove_local_images bozemanpass/backup
    $TEST_TARGET_STACK fetch repo github.com/bozemanpass/backup-stack
    $TEST_TARGET_STACK prepare --stack ${backup_stack}
    $TEST_TARGET_STACK prepare --stack ${s3_stack}
    $TEST_TARGET_STACK init --stack ${backup_stack} --output "$test_backup_spec"
    $TEST_TARGET_STACK init --stack ${s3_stack} --output "$test_s3_spec"
    spec_args=(--spec-file "$test_backup_spec" --spec-file "$test_s3_spec" "${spec_args[@]}")
fi

# Deploy.
stop_deployment_on_exit "$test_deployment_dir"
$TEST_TARGET_STACK deploy "${spec_args[@]}" --deployment-dir "$test_deployment_dir"
if [ ! -d "$test_deployment_dir" ]; then
    fail "deploy create test: FAILED - deployment directory not present"
fi
echo "deploy create test: passed"

push_images_if_needed "$test_deployment_dir"

$TEST_TARGET_STACK manage --dir "$test_deployment_dir" start
wait_for_running $TEST_BACKUP_SERVICE_COUNT $TEST_START_CHECK_LIMIT
wait_for_backup_store

# 1. Write a known payload into the app's data volume (via the app).
deployment_exec app "echo ${payload} > /data/payload.txt"
echo "wrote payload: ${payload}"

# 2. Take a backup. The engine creates the repository on first use and waits for a cold
#    object store itself, so this is not wrapped in a long readiness loop -- doing so
#    would multiply with that wait and stretch a failure into hours. A couple of attempts
#    cover a transient post-readiness hiccup; genuine unavailability fails promptly.
backed_up=
for i in {1..3}; do
    if $TEST_TARGET_STACK manage --dir "$test_deployment_dir" backup now; then backed_up=1; break; fi
    echo "backup attempt ${i} failed, retrying"
    sleep 5
done
if [ -z "$backed_up" ]; then
    fail "Backup test: FAILED"
fi
echo "Backup test: passed"

# 3. Simulate data loss by wiping the app's data volume, through the app itself: it is
#    the one container that mounts the volume read-write on every target.
deployment_exec app "rm -rf /data/payload.txt"
gone=$( deployment_exec app "ls /data" || true )
if [[ "$gone" == *"payload.txt"* ]]; then
    fail "Simulate data loss: FAILED (payload still present)"
fi
echo "Simulate data loss: passed (payload gone)"

# 4. Restore from the latest snapshot.
$TEST_TARGET_STACK manage --dir "$test_deployment_dir" backup restore

# 5. Assert the payload came back, reading it through the app.
restored=$( deployment_exec app "cat /data/payload.txt" || true )
if [[ "$restored" == *"$payload"* ]]; then
    echo "Restore content test: passed"
else
    fail "Restore content test: FAILED (expected '${payload}', got '${restored}')"
fi

# 6. Assert the volume the stack marks `@stack backup-exclude` was not captured, and the
#    one next to it was. `backup list` reports the volumes each snapshot holds, which is
#    the same question on both targets even though the exclusion reaches the engine by
#    different routes (a mount the backup container never gets on Docker, a PVC
#    annotation K8up reads on Kubernetes).
snapshots=$( $TEST_TARGET_STACK manage --dir "$test_deployment_dir" backup list )
echo "snapshots:"
echo "$snapshots"
if [[ "$snapshots" == *"app-data2"* ]]; then
    fail "Exclude annotation test: FAILED (app-data2 was backed up)"
fi
if [[ "$snapshots" != *"app-data"* ]]; then
    fail "Exclude annotation test: FAILED (app-data missing from the backup)"
fi
echo "Exclude annotation test: passed (app-data2 excluded, app-data backed up)"

# 6b. Assert the `@stack backup-command` dump was captured. The stack annotates the app
#     with a dump command (cat of the payload file, standing in for a database dump)
#     whose stdout the backup stores as a snapshot of its own. Where that snapshot shows
#     up differs by engine: the Docker target's backup container collects dumps under a
#     _dumps directory it backs up like a volume (so its content can also be read back
#     directly), while K8up stores the command output as a snapshot named for the pod,
#     with the annotated file extension.
if [ -n "$TEST_BACKUP_MIX_IN" ]; then
    if [[ "$snapshots" != *"_dumps"* ]]; then
        fail "Backup command test: FAILED (no _dumps snapshot in the list)"
    fi
    dumped=$( deployment_exec backup "cat /data/_dumps/app.txt" || true )
    if [[ "$dumped" != *"$payload"* ]]; then
        fail "Backup command test: FAILED (expected dump content '${payload}', got '${dumped}')"
    fi
else
    if [[ "$snapshots" != *".txt"* ]]; then
        fail "Backup command test: FAILED (no .txt dump snapshot in the list)"
    fi
fi
echo "Backup command test: passed (dump captured)"

# 7. Seed a *second*, independent deployment from the first one's backups. This is what
#    recovers a deployment whose cluster is gone, and what makes several copies of one
#    dataset -- so what it proves is that a backup is restorable by something other than
#    the deployment that wrote it, which restoring in place cannot show.
#
#    Only where a second deployment can reach the object store: the Docker target's store
#    lives inside the first deployment and publishes nothing (see select_backup_target).
if [ -n "$TEST_BACKUP_CAN_SEED" ]; then
    seeded_deployment_dir=$STACK_TEST_DIR/${deployment_dir_name}-seeded
    # The source deployment's name is its repository's name in the bucket.
    source_deployment=$( grep "^cluster-id:" "$test_deployment_dir/deployment.yml" | awk '{print $2}' )
    echo "seeding a new deployment from ${source_deployment}"

    $TEST_TARGET_STACK deploy --spec-file "$test_app_spec" --deployment-dir "$seeded_deployment_dir"

    # From here the teardown has two deployments to stop, and the second one is the one
    # being asserted about -- so the helpers are pointed at it and the first is stopped by
    # the extra cleanup. Done before it is started, so that a failure starting it still
    # tears it down.
    first_deployment_dir=$test_deployment_dir
    stop_first_deployment () {
        $TEST_TARGET_STACK manage --dir "$first_deployment_dir" stop --delete-volumes
    }
    TEST_EXTRA_CLEANUP=stop_first_deployment
    stop_deployment_on_exit "$seeded_deployment_dir"

    push_images_if_needed "$seeded_deployment_dir"
    $TEST_TARGET_STACK manage --dir "$seeded_deployment_dir" start
    wait_for_running $TEST_BACKUP_SERVICE_COUNT $TEST_START_CHECK_LIMIT

    empty=$( deployment_exec app "cat /data/payload.txt" 2>/dev/null || true )
    if [[ "$empty" == *"$payload"* ]]; then
        fail "Seed test: FAILED (the new deployment already had the payload before restoring)"
    fi

    $TEST_TARGET_STACK manage --dir "$seeded_deployment_dir" backup restore --from "$source_deployment"

    seeded=$( deployment_exec app "cat /data/payload.txt" || true )
    if [[ "$seeded" != *"$payload"* ]]; then
        fail "Seed test: FAILED (expected '${payload}', got '${seeded}')"
    fi
    echo "Seed test: passed (a second deployment restored the first one's backup)"
fi

# The registered teardown stops the deployment(s) and deletes their volumes.
echo "Test passed"
