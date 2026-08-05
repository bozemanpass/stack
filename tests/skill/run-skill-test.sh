#!/usr/bin/env bash
# Replays the quickstart taught by skills/deploy-with-stack/SKILL.md against the
# fixture project in ./fixture: build the images, init a compose spec, deploy,
# start, verify with a real HTTP request, stop.  If this fails, either the skill
# or the product changed and the two have diverged.
set -e
if [ -n "$STACK_SCRIPT_DEBUG" ]; then
  set -x
  echo "Environment variables:"
  env
fi

script_dir=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# Test the most recent package by default (same convention as the deploy test);
# override with TEST_TARGET_SO to run e.g. "uv run stack" in development.
if [ -z "$TEST_TARGET_SO" ]; then
  TEST_TARGET_SO=$( ls -t1 ./package/stack* | head -1 )
fi
echo "Testing this package: $TEST_TARGET_SO"

STACK_TEST_DIR=~/stack-test/skill-test-dir
export STACK_REPO_BASE_DIR=${STACK_TEST_DIR}/repo-base-dir
test_deployment_dir=$STACK_TEST_DIR/deployment
test_spec=$STACK_TEST_DIR/spec.yml

rm -rf $STACK_TEST_DIR 2>/dev/null || true
if [ -d "$STACK_TEST_DIR" ]; then
  # A previous run's database volume data is root-owned; remove it via a container
  docker run --rm -v $STACK_TEST_DIR:/cleanup alpine sh -c "rm -rf /cleanup/* /cleanup/.[!.]*"
  rm -rf $STACK_TEST_DIR
fi
mkdir -p $STACK_REPO_BASE_DIR

# The skill's scenario is a user project in its own git repository; stack.yml
# resolution requires a git checkout with a remote, so copy the fixture project
# out of this repo and make it one.
project_dir=$STACK_TEST_DIR/myproject
cp -r $script_dir/fixture/myproject $project_dir
git init -q $project_dir
git -C $project_dir remote add origin https://github.com/example/skillfixture.git
git -C $project_dir add .
git -C $project_dir -c user.email=test@example.com -c user.name="Skill Test" commit -q -m "fixture"

stop_stack_exit () {
  if [ -d "$test_deployment_dir" ]; then
    $TEST_TARGET_SO manage --dir $test_deployment_dir stop --delete-volumes
  fi
}

trap stop_stack_exit EXIT

wait_for_running () {
  local how_many=$1
  local running=0
  local check=0
  local check_limit=10
  while [ $running -lt $how_many ] && [ $check -lt $check_limit ]; do
      check=$((check + 1))
      running=$($TEST_TARGET_SO manage --dir $test_deployment_dir status | grep -ic "running")
      if [ $running -lt $how_many ]; then
          echo "skill test: waiting for services to start..."
          sleep 5
      fi
  done

  if [ $running -lt $how_many ]; then
      echo "skill test: FAILED - not all services started"
      exit 1
  fi
}

# Step 2 of the skill: build the images
$TEST_TARGET_SO build containers --stack $project_dir/stack
if ! docker images | grep -q "bpitest/skill-backend"; then
  echo "skill test: FAILED - built image not found"
  exit 1
fi
echo "skill test build: passed"

# Step 3 of the skill: generate a spec and deploy
$TEST_TARGET_SO init --stack $project_dir/stack \
  --output $test_spec \
  --deploy-to compose \
  --map-ports-to-host localhost-same \
  --config POSTGRES_PASSWORD=example
if [ ! -f "$test_spec" ]; then
  echo "skill test: FAILED - spec file not present"
  exit 1
fi

$TEST_TARGET_SO deploy --spec-file $test_spec --deployment-dir $test_deployment_dir
if [ ! -d "$test_deployment_dir" ]; then
  echo "skill test: FAILED - deployment directory not present"
  exit 1
fi
echo "skill test deploy: passed"

# Step 4 of the skill: start and verify with a real request
$TEST_TARGET_SO manage --dir $test_deployment_dir start
wait_for_running 2
$TEST_TARGET_SO manage --dir $test_deployment_dir ps
$TEST_TARGET_SO manage --dir $test_deployment_dir port backend 8080

set +e
try=0
rc=1
while [ $rc -ne 0 ] && [ $try -lt 10 ]; do
  try=$((try + 1))
  curl -s --fail http://localhost:8080/index.html | grep -q "skill-fixture-ok"
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "skill test: waiting for HTTP..."
    sleep 5
  fi
done
set -e
if [ $rc -ne 0 ]; then
  echo "skill test http: FAILED"
  exit 1
fi
echo "skill test http: passed"

$TEST_TARGET_SO manage --dir $test_deployment_dir stop --delete-volumes
trap - EXIT

echo "Test passed"
