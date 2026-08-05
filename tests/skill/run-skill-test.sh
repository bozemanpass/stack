#!/usr/bin/env bash
# Replays the quickstart taught by skills/deploy-with-stack/SKILL.md against the
# fixture project in ./fixture: build the images, init a compose spec, deploy,
# start, verify with a real HTTP request, stop.  If this fails, either the skill
# or the product changed and the two have diverged.
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

script_dir=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# Test the most recent package by default; override with TEST_TARGET_STACK to
# run e.g. "uv run stack" in development.
select_test_target "$@"

setup_test_dir skill-test-dir
test_deployment_dir=$STACK_TEST_DIR/deployment
test_spec=$STACK_TEST_DIR/spec.yml

# The skill's scenario is a user project in its own git repository; stack.yml
# resolution requires a git checkout with a remote, so copy the fixture project
# out of this repo and make it one.
project_dir=$STACK_TEST_DIR/myproject
cp -r $script_dir/fixture/myproject $project_dir
git init -q $project_dir
git -C $project_dir remote add origin https://github.com/example/skillfixture.git
git -C $project_dir add .
git -C $project_dir -c user.email=test@example.com -c user.name="Skill Test" commit -q -m "fixture"

# Step 2 of the skill: build the images
$TEST_TARGET_STACK build containers --stack $project_dir/stack
if ! docker images | grep -q "bpitest/skill-backend"; then
  fail "skill test: FAILED - built image not found"
fi
echo "skill test build: passed"

# Step 3 of the skill: generate a spec and deploy
$TEST_TARGET_STACK init --stack $project_dir/stack \
  --output $test_spec \
  --deploy-to compose \
  --map-ports-to-host localhost-same \
  --config POSTGRES_PASSWORD=example
if [ ! -f "$test_spec" ]; then
  fail "skill test: FAILED - spec file not present"
fi

stop_deployment_on_exit $test_deployment_dir
$TEST_TARGET_STACK deploy --spec-file $test_spec --deployment-dir $test_deployment_dir
if [ ! -d "$test_deployment_dir" ]; then
  fail "skill test: FAILED - deployment directory not present"
fi
echo "skill test deploy: passed"

# Step 4 of the skill: start and verify with a real request
$TEST_TARGET_STACK manage --dir $test_deployment_dir start
wait_for_running 2
$TEST_TARGET_STACK manage --dir $test_deployment_dir ps
$TEST_TARGET_STACK manage --dir $test_deployment_dir port backend 8080

wait_for_content http://localhost:8080/index.html "skill-fixture-ok" 10
echo "skill test http: passed"

# The registered teardown stops the deployment and deletes its volumes.
echo "Test passed"
