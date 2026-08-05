#!/usr/bin/env bash
# End-to-end test of the backup/restore feature on the Docker (compose) target.
#
# Flow: deploy an app (holding data in a volume) + a local S3 store (SeaweedFS) + the
# mixed-in backup stack -> write a known payload -> take a restic backup -> wipe the data
# -> restore from the backup -> assert the payload came back (read via the app). Also
# relies on the s3 store's own volume being excluded from backup (@stack backup-exclude)
# so it is not captured.
#
# Requires Docker. Run from the repo root, either:
#   ./tests/backup/run-test.sh                # uses the built shiv package in ./package
#   ./tests/backup/run-test.sh from-path      # uses `stack` from PATH (dev mode)
#
# NOTE: this fetches the test stacks and the backup stack from GitHub, so the
# `test-backup-stack` additions in bozemanpass/stack-test-stacks and the
# bozemanpass/backup-stack repo must be pushed for this to run.
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

require_commands docker

select_test_target "$@"

app_stack="test-backup-stack"
backup_stack="backup"
deployment_dir_name="${app_stack}-deployment"
app_spec="${app_stack}-spec.yml"
backup_spec="${backup_stack}-spec.yml"

# Ambient backup configuration (sourced from the environment by the stack tool).
export STACK_BACKUP=true
export STACK_BACKUP_S3_ENDPOINT=http://s3:8333
export STACK_BACKUP_S3_BUCKET=stack-backups

payload="backup-test-payload-$$"   # a value unique to this run

setup_test_dir backup-test-dir

# Force a rebuild of the backup image so the test exercises current sources.
remove_local_images bozemanpass/backup

# Fetch and prepare the stacks.
$TEST_TARGET_STACK fetch repo github.com/bozemanpass/stack-test-stacks
$TEST_TARGET_STACK fetch repo github.com/bozemanpass/backup-stack
$TEST_TARGET_STACK prepare --stack ${app_stack}
$TEST_TARGET_STACK prepare --stack ${backup_stack}

test_deployment_dir=$STACK_TEST_DIR/${deployment_dir_name}
test_app_spec=$STACK_TEST_DIR/${app_spec}
test_backup_spec=$STACK_TEST_DIR/${backup_spec}

# Init the app stack (Docker target - no --deploy-to k8s-kind).
$TEST_TARGET_STACK init --stack ${app_stack} --output "$test_app_spec"

# Init the backup stack. The restic password + S3 credentials are passed as config so they
# reach the backup container via the shared config.env (SeaweedFS ignores the creds but
# restic requires them to be set).
$TEST_TARGET_STACK init --stack ${backup_stack} --output "$test_backup_spec" \
    --config RESTIC_PASSWORD=test-restic-password \
    --config AWS_ACCESS_KEY_ID=test-access-key \
    --config AWS_SECRET_ACCESS_KEY=test-secret-key

# Deploy, mixing in the backup stack.
stop_deployment_on_exit "$test_deployment_dir"
$TEST_TARGET_STACK deploy \
    --spec-file "$test_backup_spec" \
    --spec-file "$test_app_spec" \
    --deployment-dir "$test_deployment_dir"
if [ ! -d "$test_deployment_dir" ]; then
    fail "deploy create test: FAILED - deployment directory not present"
fi
echo "deploy create test: passed"

$TEST_TARGET_STACK manage --dir "$test_deployment_dir" start
wait_for_containers_started

# 1. Write a known payload into the app's data volume (via the app).
deployment_exec app "echo ${payload} > /data/payload.txt"
echo "wrote payload: ${payload}"

# 2. Take a backup. backup.sh's ensure_repo already waits for the S3 store to finish
#    warming up (and creates the restic repository on first use), so we do NOT wrap this in
#    a long readiness loop here - doing so would multiply with ensure_repo's own retry and
#    stretch a failure into hours. A couple of attempts cover a transient post-readiness
#    hiccup; genuine unavailability fails promptly.
backed_up=
for i in {1..3}; do
    if deployment_exec backup "/scripts/backup.sh"; then backed_up=1; break; fi
    echo "backup attempt ${i} failed, retrying"
    sleep 5
done
if [ -z "$backed_up" ]; then
    fail "Backup test: FAILED"
fi
echo "Backup test: passed"

# 3. Simulate data loss by wiping the app volume (through the backup container's rw mount).
deployment_exec backup "rm -rf /backup/app-data/*"
gone=$( deployment_exec backup "ls /backup/app-data" || true )
if [[ "$gone" == *"payload.txt"* ]]; then
    fail "Simulate data loss: FAILED (payload still present)"
fi
echo "Simulate data loss: passed (payload gone)"

# 4. Restore from the latest snapshot.
deployment_exec backup "/scripts/restore.sh latest"

# 5. Assert the payload came back, reading it through the app.
restored=$( deployment_exec app "cat /data/payload.txt" || true )
if [[ "$restored" == *"$payload"* ]]; then
    echo "Restore content test: passed"
else
    fail "Restore content test: FAILED (expected '${payload}', got '${restored}')"
fi

# 6. Assert the excluded s3 store volume was NOT mounted into / captured by the backup.
listing=$( deployment_exec backup "ls /backup" || true )
if [[ "$listing" == *"s3-data"* ]]; then
    fail "Exclude annotation test: FAILED (s3-data was backed up)"
fi
if [[ "$listing" != *"app-data"* ]]; then
    fail "Exclude annotation test: FAILED (app-data missing from backup)"
fi
echo "Exclude annotation test: passed (s3-data excluded, app-data backed up)"

# The registered teardown stops the deployment and deletes its volumes.
echo "Test passed"
