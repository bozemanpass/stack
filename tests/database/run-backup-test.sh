#!/usr/bin/env bash
#
# Check that a database survives the deployment holding it being destroyed, by way
# of a logical dump.
#
# This is the assertion the database test makes -- the test client reports on each
# start whether its data is already there, so a first start says "does not exist"
# and a later one must say "already exists" -- carried across a wider gap.  The
# database test stops and starts one deployment, and what it proves is that the
# volume outlives the containers.  Here the deployment itself is destroyed,
# volumes and directory and all, and a *new* deployment of the same stack is filled
# from the backup the first one took.
#
# What makes this different from the backup test, which also restores into a second
# deployment, is *what is in the backup*.  The database stack excludes its live data
# directory and instead has a `@stack backup-command` dump taken at backup time, so
# the repository holds no database files at all -- only a pg_dump.  That is the
# arrangement the backup documentation tells the author of a database component to
# use, for two reasons this test depends on: a file-level copy of a live database
# can be torn, and carrying one next to the dump would roughly double the size of
# every backup for a second, worse copy of the same data.  So the restore here is
# not a file-level restore of a database: it fills the volume the dump lives in, and
# the database is rebuilt from it with pg_restore.  Nothing else brings the data
# back, since nothing else was kept.
#
# It lives beside the database test rather than inside it deliberately.  The
# database test is about where the bytes live and needs nothing but the stack it
# deploys; giving it a backup step would make every run of it depend on an object
# store and a backup engine that have nothing to do with what it checks.  The two
# do run in the same CI job, since the second reuses the first's stack and images.
#
# Requires Docker.  Run from the repo root, either:
#   ./tests/database/run-backup-test.sh            # uses the built shiv package in ./package
#   ./tests/database/run-backup-test.sh from-path  # uses `stack` from PATH (dev mode)
#
# Docker target only, and unlike the kind exclusion in select_backup_target the
# reason is this test rather than the engine.  The assertion only means something if
# the new deployment is filled *before* its test client has ever run: let the client
# start first and it creates the data itself, and then "already exists" is true
# whether or not anything was restored.  On the Docker target the deployment can be
# brought up a service at a time, so there is a moment where the database and the
# backup engine are running and the client is not.  On Kubernetes the volumes being
# restored into are PVCs that only come into being when the deployment starts, so
# there is no equivalent moment, and getting one would mean a stack whose client can
# be told to wait -- a different fixture than the database test's.
#
# NOTE: this fetches the test stacks and the backup stack from GitHub, so the
# backup annotations on `test-database-stack` in bozemanpass/stack-test-stacks must
# be pushed for this to run.
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

require_commands docker

select_test_target "$@"
select_deploy_target
if [ "$TEST_TARGET_ENV" != "compose" ]; then
    fail "Error: the database backup test only runs against the compose target, not $TEST_TARGET_ENV (see the comment at the top of this script)"
fi
# "external": the object store has to outlive the deployment that backs up to it,
# which is the whole point here, so it is deployed separately rather than mixed in.
select_backup_target external

stack="test-database-stack"
backup_stack="backup"
spec_file=${stack}-spec.yml
backup_spec_file=${backup_stack}-spec.yml

# Where the stack's `@stack backup-command` writes its dump, and where a restore
# puts it back: a volume of the database's own, so that pg_restore can read it from
# inside the database container.
dump_volume="db-dumps"
dump_file="/dumps/test-db.dump"

# Wait until the database is accepting connections.  `status` reports a compose
# container as running as soon as it is up, which for a database that is still
# recovering or still running initdb is too early to restore into.
wait_for_database () {
    local check_limit=${1:-30}
    local check=0
    while [ $check -lt $check_limit ]; do
        check=$((check + 1))
        if deployment_exec database "pg_isready -U test-user -d test-db" > /dev/null 2>&1; then
            return
        fi
        echo "waiting for the database to accept connections..."
        sleep 5
    done
    fail "waiting for the database: FAILED"
}

setup_test_dir database-backup-test-dir
# Any local copy of the test containers would be reused instead of built.
remove_local_images bozemanpass/test-database-client
remove_local_images bozemanpass/test-database-container
remove_local_images bozemanpass/backup

echo "Fetching test stack repo into: $STACK_REPO_BASE_DIR"
$TEST_TARGET_STACK fetch repo github.com/bozemanpass/stack-test-stacks
$TEST_TARGET_STACK fetch repo github.com/bozemanpass/backup-stack
$TEST_TARGET_STACK prepare --stack ${stack}
$TEST_TARGET_STACK prepare --stack ${backup_stack}

test_deployment_spec=$STACK_TEST_DIR/${spec_file}
test_backup_spec=$STACK_TEST_DIR/${backup_spec_file}
first_deployment_dir=$STACK_TEST_DIR/${stack}-deployment
second_deployment_dir=$STACK_TEST_DIR/${stack}-deployment-restored

$TEST_TARGET_STACK init --stack ${stack} $TEST_INIT_ARGS --output $test_deployment_spec
$TEST_TARGET_STACK init --stack ${backup_stack} --output $test_backup_spec

# The store first: it is where the backup goes, and it is deliberately not part of
# either deployment of the stack under test.
start_object_store_deployment

# --- the first deployment: load it, dump it, destroy it ----------------------

stop_deployment_on_exit $first_deployment_dir
$TEST_TARGET_STACK deploy --spec-file $test_backup_spec --spec-file $test_deployment_spec \
    --deployment-dir $first_deployment_dir
$TEST_TARGET_STACK manage --dir $first_deployment_dir start
# The stack's database and test client, plus the backup container.
wait_for_running $(( 2 + TEST_BACKUP_EXTRA_SERVICES )) $TEST_START_CHECK_LIMIT
wait_for_backup_store

wait_for_log_content "Database test client: test complete"
log_output_1=$( $TEST_TARGET_STACK manage --dir $first_deployment_dir logs )
if [[ "$log_output_1" != *"Database test client: test data does not exist"* ]]; then
    fail "Create database content test: FAILED"
fi
echo "Create database content test: passed"

# The name of the repository the backup lands in, which is the only thing about this
# deployment the next one is given.  Read before the backup rather than after, so
# that a failure to find it is not mistaken for a backup that went nowhere.
source_deployment=$( grep "^cluster-id:" $first_deployment_dir/deployment.yml | awk '{print $2}' )
if [ -z "$source_deployment" ]; then
    fail "Backup test: FAILED - no cluster-id in the deployment"
fi

# The engine creates the repository on first use and waits for a cold object store
# itself, so this is not wrapped in a long readiness loop; a couple of attempts
# cover a transient post-readiness hiccup.
backed_up=
for i in {1..3}; do
    if $TEST_TARGET_STACK manage --dir $first_deployment_dir backup now; then backed_up=1; break; fi
    echo "backup attempt ${i} failed, retrying"
    sleep 5
done
if [ -z "$backed_up" ]; then
    fail "Backup test: FAILED"
fi

# The dump was taken by the backup itself, inside the database container, so it has
# to be there afterwards -- a `backup now` that quietly skipped its hook would leave
# an empty volume backed up and look no different from here.
dumped=$( deployment_exec database "ls -l ${dump_file}" || true )
if [[ "$dumped" != *"${dump_file}"* ]]; then
    fail "Dump test: FAILED - ${dump_file} was not written by the backup"
fi
echo "Dump test: passed (${dumped})"

# What the repository holds is the point of this test: the dump's volume, and *not*
# the database's data directory.  The exclusion is what keeps a backup from carrying
# a second copy of the same data, so a backup that quietly included the data files
# would still restore fine below and would still be wrong.
snapshots=$( $TEST_TARGET_STACK manage --dir $first_deployment_dir backup list )
echo "snapshots:"
echo "$snapshots"
if [[ "$snapshots" != *"${dump_volume}"* ]]; then
    fail "Backup test: FAILED - the dump volume is not in the backup"
fi
if [[ "$snapshots" == *"db-data"* ]]; then
    fail "Backup test: FAILED - the database's data directory was backed up despite being excluded"
fi
echo "Backup test: passed (dump backed up, data directory excluded, from ${source_deployment})"

# Destroy it: containers, volumes and deployment directory.  From here the only
# thing left of it is the repository in the object store -- which holds a pg_dump
# and no database files at all.
destroy_deployment $first_deployment_dir
echo "Destroy deployment test: passed"

# --- the second deployment: restore the dump into it, and rebuild from it ----

$TEST_TARGET_STACK deploy --spec-file $test_backup_spec --spec-file $test_deployment_spec \
    --deployment-dir $second_deployment_dir
stop_deployment_on_exit $second_deployment_dir

# Start the backup container and the database, but not the test client.  The backup
# container is the engine, so it has to be up to restore; the database has to be up
# for pg_restore to have something to restore into, and comes up empty, since its
# data directory was never in the backup.  The client stays down so that the data it
# reports on is the restored data and nothing it created itself -- see the note at
# the top of this script.
$TEST_TARGET_STACK manage --dir $second_deployment_dir start backup database
wait_for_running 2 $TEST_START_CHECK_LIMIT
wait_for_database

# Restore: this fills the dump's volume, which the database container mounts.  It
# does not put a database back -- there is no database in the repository to put.
$TEST_TARGET_STACK manage --dir $second_deployment_dir backup restore --from "$source_deployment"
restored=$( deployment_exec database "ls -l ${dump_file}" || true )
if [[ "$restored" != *"${dump_file}"* ]]; then
    fail "Restore test: FAILED - ${dump_file} not present after the restore"
fi
echo "Restore test: passed (${restored})"

# Rebuild the database from the dump, in the database's own container.  This is the
# manual half of a dump-based recovery: `backup restore` puts volumes back, and only
# the application knows how to replay a logical dump.
$TEST_TARGET_STACK manage --dir $second_deployment_dir exec database \
    "pg_restore --exit-on-error -U test-user -d test-db ${dump_file}"
echo "pg_restore test: passed"

# Now start the client, which reports what it finds in the rebuilt database.
$TEST_TARGET_STACK manage --dir $second_deployment_dir start
wait_for_running $(( 2 + TEST_BACKUP_EXTRA_SERVICES )) $TEST_START_CHECK_LIMIT
wait_for_log_content "Database test client: test complete"

log_output_2=$( $TEST_TARGET_STACK manage --dir $second_deployment_dir logs )
if [[ "$log_output_2" == *"Database test client: test data already exists"* ]]; then
    echo "Restore database content test: passed"
else
    fail "Restore database content test: FAILED"
fi

# The registered teardown stops the second deployment and the object store.
echo "Test passed"
