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
set -e
if [ -n "$STACK_SCRIPT_DEBUG" ]; then
    set -x
fi

if ! command -v docker &> /dev/null; then
    echo "Error: 'docker' is not installed or not available on the PATH"
    exit 1
fi

if [ "$1" == "from-path" ]; then
    TEST_TARGET_STACK="stack"
else
    TEST_TARGET_STACK=$( ls -t1 ./package/stack* | head -1 )
fi

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

# Run a command inside a deployment container. The stack `exec` wraps the command in
# `sh -c`, so the whole command must be passed as a single argument.
dexec () { $TEST_TARGET_STACK manage --dir "$test_deployment_dir" exec "$1" "$2"; }

# Containers write into the bind-mounted volume dirs as root, so the resulting files cannot
# be removed by the (non-root) host user. Remove such a dir via a throwaway container.
force_rm () {
    if [ -d "$1" ]; then
        docker run --rm -v "$(dirname "$1")":/w alpine rm -rf "/w/$(basename "$1")" || rm -rf "$1"
    fi
}

cleanup_exit () {
    $TEST_TARGET_STACK manage --dir "$test_deployment_dir" stop --delete-volumes || true
    exit 1
}

wait_for_pods_started () {
    for i in {1..50}; do
        local ps_output
        ps_output=$( $TEST_TARGET_STACK manage --dir "$test_deployment_dir" ps )
        if [[ "$ps_output" == *"id:"* ]]; then
            return
        fi
        sleep 5
    done
    echo "waiting for pods to start: FAILED"
    cleanup_exit
}

STACK_TEST_DIR=~/stack-test/backup-test-dir
export STACK_REPO_BASE_DIR=${STACK_TEST_DIR}/repo-base-dir
echo "Testing this package: $TEST_TARGET_STACK"
$TEST_TARGET_STACK version
echo "Using test directory: $STACK_TEST_DIR"
force_rm "$STACK_TEST_DIR"
mkdir -p "$STACK_REPO_BASE_DIR"

# Force a rebuild of the backup image so the test exercises current sources.
existing=$(docker image ls -q --filter=reference=bozemanpass/backup | uniq)
if [ -n "$existing" ]; then docker image rm -f ${existing} || true; fi

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
$TEST_TARGET_STACK deploy \
    --spec-file "$test_backup_spec" \
    --spec-file "$test_app_spec" \
    --deployment-dir "$test_deployment_dir"
if [ ! -d "$test_deployment_dir" ]; then
    echo "deploy create test: deployment directory not present"
    echo "deploy create test: FAILED"
    exit 1
fi
echo "deploy create test: passed"

$TEST_TARGET_STACK manage --dir "$test_deployment_dir" start
wait_for_pods_started

# 1. Write a known payload into the app's data volume (via the app).
dexec app "echo ${payload} > /data/payload.txt"
echo "wrote payload: ${payload}"

# 2. Take a backup, retrying until the S3 store has finished starting up. backup.sh creates
#    the restic repository on first use (restic auto-creates the bucket on SeaweedFS).
backed_up=
for i in {1..50}; do
    if dexec backup "/scripts/backup.sh"; then backed_up=1; break; fi
    echo "waiting for backup to succeed (s3 warming up): ${i}"
    sleep 5
done
if [ -z "$backed_up" ]; then
    echo "Backup test: FAILED"
    cleanup_exit
fi
echo "Backup test: passed"

# 3. Simulate data loss by wiping the app volume (through the backup container's rw mount).
dexec backup "rm -rf /backup/app-data/*"
gone=$( dexec backup "ls /backup/app-data" || true )
if [[ "$gone" == *"payload.txt"* ]]; then
    echo "Simulate data loss: FAILED (payload still present)"
    cleanup_exit
fi
echo "Simulate data loss: passed (payload gone)"

# 4. Restore from the latest snapshot.
dexec backup "/scripts/restore.sh latest"

# 5. Assert the payload came back, reading it through the app.
restored=$( dexec app "cat /data/payload.txt" || true )
if [[ "$restored" == *"$payload"* ]]; then
    echo "Restore content test: passed"
else
    echo "Restore content test: FAILED (expected '${payload}', got '${restored}')"
    cleanup_exit
fi

# 6. Assert the excluded s3 store volume was NOT mounted into / captured by the backup.
listing=$( dexec backup "ls /backup" || true )
if [[ "$listing" == *"s3-data"* ]]; then
    echo "Exclude annotation test: FAILED (s3-data was backed up)"
    cleanup_exit
fi
if [[ "$listing" != *"app-data"* ]]; then
    echo "Exclude annotation test: FAILED (app-data missing from backup)"
    cleanup_exit
fi
echo "Exclude annotation test: passed (s3-data excluded, app-data backed up)"

$TEST_TARGET_STACK manage --dir "$test_deployment_dir" stop --delete-volumes
echo "Test passed"
