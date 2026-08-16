#!/usr/bin/env bash
#
# Check that a database survives the deployment holding it being destroyed, by way
# of a logical dump.
#
# The database test stops and starts one deployment, and what it proves is that the
# volume outlives the containers.  Here the deployment itself is destroyed, volumes
# and directory and all, and the database is rebuilt in a *new* deployment from the
# backup the first one took.
#
# What makes this different from the backup test, which also restores into a second
# deployment, is what is in the backup.  The database stack excludes its live data
# directory and instead has a `@stack backup-command` pg_dump taken at backup time,
# writing into a volume of the database's own, so the repository holds no database
# files at all.  That is what the backup documentation tells the author of a
# database component to do, for two reasons this test depends on: a file-level copy
# of a live database can be torn, and carrying one next to the dump would roughly
# double the size of every backup for a second, worse copy of the same data.  So
# the restore here is not a file-level restore of a database: it fills the volume
# the dump lives in, and pg_restore rebuilds the database from it.
#
# The assertion is a row written by this run and by nothing else.  That matters
# because the new deployment's test client comes up and creates the *stack's* test
# data for itself, exactly as it does on a first deployment -- so "the data is
# there" is true before anything is restored, and only data that could not have
# come from anywhere but the backup can distinguish a restore that worked.  The
# test checks the row is absent from the new deployment before the restore and
# present after it.
#
# Runs against compose and remote (see select_backup_target in tests/lib/common.sh
# for why there is no kind leg).  Both are worth running because the engines are
# different -- restic in a mixed-in backup container on the Docker target, K8up on
# a cluster -- while what the test asks of them is identical, down to the name the
# dump is stored under.
#
#   STACK_TEST_TARGET=compose ./tests/database/run-backup-test.sh   # the default
#   STACK_TEST_TARGET=remote  ./tests/database/run-backup-test.sh   # see tests/k3s-deploy
#
# Recovery here is deliberately *external*: the dump is read out of the repository
# with the bare restic CLI, from outside either deployment, and replayed into the
# database with psql.  That is what an operator does today -- `backup restore` fills
# volumes, and a dump is not a volume -- and it doubles as a check on the claim that
# a stack's backups are readable without the stack tool at all.  It is also the one
# route that is the same on both targets: on a cluster there is no backup container
# to read a dump out of.
#
# It lives beside the database test rather than inside it deliberately.  The
# database test is about where the bytes live and needs nothing but the stack it
# deploys; giving it a backup step would make every run of it depend on an object
# store and a backup engine that have nothing to do with what it checks.  On
# compose the two run in the same CI job, since this one reuses the first's stack
# and images.
#
# Requires Docker.  Run from the repo root, either:
#   ./tests/database/run-backup-test.sh            # uses the built shiv package in ./package
#   ./tests/database/run-backup-test.sh from-path  # uses `stack` from PATH (dev mode)
#
# NOTE: this fetches the test stacks (and, on the Docker target, the backup stack)
# from GitHub, so the backup annotations on `test-database-stack` in
# bozemanpass/stack-test-stacks must be pushed for this to run.
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

require_commands docker

select_test_target "$@"
select_deploy_target
# "external": the object store has to outlive the deployment that backs up to it,
# which is the whole point here.  On a cluster it already does; on the Docker
# target this moves it out of the deployment and into one of its own.
select_backup_target external

stack="test-database-stack"
backup_stack="backup"
spec_file=${stack}-spec.yml
backup_spec_file=${backup_stack}-spec.yml

# The dump is not a file anywhere in the deployment: the engine streams the dump
# command's stdout straight into a snapshot of its own, stored under this name --
# `<deployment>-<service>.<extension>`, which both engines agree on.  The deployment
# half is only known once the first deployment exists, so this is the tail of it.
dump_name_suffix="-database.sql"

# The row this run is identified by.  Written into the first deployment after its
# client has created the stack's own test data, so it is in the dump and in nothing
# else -- in particular not in whatever a fresh deployment's client creates for
# itself.
payload_key="restored-by-test-$$"
payload="database-backup-test-payload-$$"

# Run a statement against the deployment's database, printing just the value:
# -t drops the header and row count, -A the column padding.
run_sql () {
    deployment_exec database "psql -U test-user -d test-db -t -A -c \"$1\""
}

setup_test_dir database-backup-test-dir
# Any local copy of the test containers would be reused instead of built.
remove_local_images bozemanpass/test-database-client
remove_local_images bozemanpass/test-database-container

echo "Fetching test stack repo into: $STACK_REPO_BASE_DIR"
$TEST_TARGET_STACK fetch repo github.com/bozemanpass/stack-test-stacks
$TEST_TARGET_STACK prepare --stack ${stack}

test_deployment_spec=$STACK_TEST_DIR/${spec_file}
test_backup_spec=$STACK_TEST_DIR/${backup_spec_file}
first_deployment_dir=$STACK_TEST_DIR/${stack}-deployment
second_deployment_dir=$STACK_TEST_DIR/${stack}-deployment-restored

$TEST_TARGET_STACK init --stack ${stack} $TEST_INIT_ARGS --output $test_deployment_spec

# Both deployments are made from the same specs.  On the Docker target that
# includes the backup stack, which is the engine there; on a cluster the engine is
# K8up and a backup container would sit idle holding no data mounts.
spec_args=(--spec-file "$test_deployment_spec")
if [ -n "$TEST_BACKUP_MIX_IN" ]; then
    remove_local_images bozemanpass/backup
    $TEST_TARGET_STACK fetch repo github.com/bozemanpass/backup-stack
    $TEST_TARGET_STACK prepare --stack ${backup_stack}
    $TEST_TARGET_STACK init --stack ${backup_stack} --output "$test_backup_spec"
    spec_args=(--spec-file "$test_backup_spec" "${spec_args[@]}")
fi

# The store first: it is where the backup goes, and it is deliberately not part of
# either deployment of the stack under test.
start_object_store_deployment

# --- the first deployment: load it, dump it, destroy it ----------------------

stop_deployment_on_exit $first_deployment_dir
$TEST_TARGET_STACK deploy "${spec_args[@]}" --deployment-dir $first_deployment_dir
push_images_if_needed $first_deployment_dir
$TEST_TARGET_STACK manage --dir $first_deployment_dir start
# The stack's database and test client, plus whatever the backup arrangement adds.
wait_for_running $(( 2 + TEST_BACKUP_EXTRA_SERVICES )) $TEST_START_CHECK_LIMIT
wait_for_backup_store

wait_for_log_content "Database test client: test complete"
log_output_1=$( $TEST_TARGET_STACK manage --dir $first_deployment_dir logs )
if [[ "$log_output_1" != *"Database test client: test data does not exist"* ]]; then
    fail "Create database content test: FAILED"
fi
echo "Create database content test: passed"

# The row that identifies this run, on top of the data the client just created.
run_sql "insert into test_table_1 values ('${payload_key}', '${payload}');"
written=$( run_sql "select value_column from test_table_1 where key_column = '${payload_key}';" )
if [[ "$written" != *"$payload"* ]]; then
    fail "Write payload test: FAILED (expected '${payload}', got '${written}')"
fi
echo "Write payload test: passed (${payload})"

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
# What the repository holds is the point of this test: the dump, and *nothing else*.
# The exclusion is what keeps a backup from also carrying a file-level copy of the
# same data -- which would roughly double its size and be the less restorable half --
# so a backup that quietly included the data directory would still recover fine below
# and would still be wrong.
dump_snapshot="${source_deployment}${dump_name_suffix}"
snapshots=$( $TEST_TARGET_STACK manage --dir $first_deployment_dir backup list )
echo "snapshots:"
echo "$snapshots"
if [[ "$snapshots" != *"${dump_snapshot}"* ]]; then
    fail "Backup test: FAILED - no ${dump_snapshot} snapshot in the backup"
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

$TEST_TARGET_STACK deploy "${spec_args[@]}" --deployment-dir $second_deployment_dir
stop_deployment_on_exit $second_deployment_dir
push_images_if_needed $second_deployment_dir
$TEST_TARGET_STACK manage --dir $second_deployment_dir start
wait_for_running $(( 2 + TEST_BACKUP_EXTRA_SERVICES )) $TEST_START_CHECK_LIMIT
wait_for_log_content "Database test client: test complete"

# It comes up as any first deployment does: its data directory was never in the
# backup, so the database is empty and the client creates the stack's test data for
# itself.  That is why the assertion below is about this run's own row and not
# about the client's report.
log_output_2=$( $TEST_TARGET_STACK manage --dir $second_deployment_dir logs )
if [[ "$log_output_2" != *"Database test client: test data does not exist"* ]]; then
    fail "New deployment test: FAILED - the new deployment did not start empty"
fi
# Whitespace-stripped and compared exactly: a substring test for "0" would also be
# satisfied by "10", and on the k8s target exec output carries a carriage return.
before=$( run_sql "select count(*) from test_table_1 where key_column = '${payload_key}';" | tr -d '[:space:]' )
if [ "$before" != "0" ]; then
    fail "New deployment test: FAILED - the payload row was already present before restoring"
fi
echo "New deployment test: passed (started empty of this run's data)"

# Read the dump out of the repository with the bare restic CLI, from outside both
# deployments -- the destroyed one and this one.  Nothing of the stack tool is
# involved: a throwaway restic container, the bucket, the repository password and the
# name of a deployment that no longer exists.  That is the recovery route an operator
# has today for a dump, and the same one on both targets.
dump_sql=$STACK_TEST_DIR/recovered.sql
docker run --rm \
    -e RESTIC_REPOSITORY="s3:${STACK_BACKUP_S3_ENDPOINT%/}/${STACK_BACKUP_S3_BUCKET}/${source_deployment}" \
    -e RESTIC_PASSWORD="$STACK_BACKUP_RESTIC_PASSWORD" \
    -e AWS_ACCESS_KEY_ID="$STACK_BACKUP_S3_KEY_ID" \
    -e AWS_SECRET_ACCESS_KEY="$STACK_BACKUP_S3_KEY" \
    restic/restic:latest dump --path "/${dump_snapshot}" latest "/${dump_snapshot}" > "$dump_sql"
if [ ! -s "$dump_sql" ]; then
    fail "Recover dump test: FAILED - nothing came out of ${dump_snapshot}"
fi
echo "Recover dump test: passed ($( wc -c < "$dump_sql" ) bytes of SQL)"

# Replay it into the running database.  `exec` has no stdin to pipe into, so the SQL
# travels as base64 in the command itself -- an artifact of the test harness, not of
# the recovery: an operator with a shell would redirect the file into psql.
#
# The dump carries --clean --if-exists, so it drops and recreates what this
# deployment's client already created, which is what replaying into a database that
# has been running looks like.
dump_b64=$( base64 -w0 < "$dump_sql" )
$TEST_TARGET_STACK manage --dir $second_deployment_dir exec database \
    "echo \"${dump_b64}\" | base64 -d | psql -v ON_ERROR_STOP=1 -U test-user -d test-db"
echo "Replay dump test: passed"

# The assertion: this run's row, which existed only in the destroyed deployment and
# could only have arrived here through the backup.
recovered=$( run_sql "select value_column from test_table_1 where key_column = '${payload_key}';" )
if [[ "$recovered" == *"$payload"* ]]; then
    echo "Restore database content test: passed"
else
    fail "Restore database content test: FAILED (expected '${payload}', got '${recovered}')"
fi

# The registered teardown stops the second deployment and the object store.
echo "Test passed"
