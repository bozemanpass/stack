#!/usr/bin/env bash
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

# Test basic stack webapp
echo "Running stack webapp test"
select_test_target "$@"
setup_test_dir webapp-test-dir
# Fetched pages are written here rather than the working directory, so a failed
# run does not leave test.* files scattered in the repo.
scratch=$STACK_TEST_DIR/fetched
mkdir -p $scratch
# Overridable for local testing against an unpushed app repo, and used by the
# test-progressive-web-app repo's own CI to run this test against a checkout of
# a change before it is merged -- a rename or a dependency bump there breaks
# this test, and the useful place to find that out is on that repo's PR.  A
# local directory works as a clone source, so the override takes a path as
# readily as a URL.
TEST_WEBAPP_REPO=${STACK_TEST_WEBAPP_REPO:-https://github.com/bozemanpass/test-progressive-web-app.git}
echo "Cloning repositories into: $STACK_REPO_BASE_DIR"
git clone $TEST_WEBAPP_REPO $STACK_REPO_BASE_DIR/test-progressive-web-app

# Likewise for the wrapper: the stack-wrapper-webapp repo's CI points this at
# its own checkout so a wrapper change is exercised against a real app before it
# is merged.  Wrappers are found by searching STACK_REPO_BASE_DIR for a
# wrapper.yml, so dropping the checkout anywhere inside it is enough.
#
# Note that a *clean* checkout may still be served from a prebuilt image: the
# base container is looked up by the wrapper repo's commit hash.  That is the
# image consumers of that commit will get, so it is the right thing to test; a
# dirty checkout, as when testing by hand, always builds locally.
if [ -n "$STACK_TEST_WRAPPER_DIR" ]; then
  echo "Using wrapper checkout: $STACK_TEST_WRAPPER_DIR"
  cp -a "$STACK_TEST_WRAPPER_DIR" $STACK_REPO_BASE_DIR/wrapper-under-test
fi

# Test webapp command execution
$TEST_TARGET_STACK webapp build --source-repo $STACK_REPO_BASE_DIR/test-progressive-web-app

CHECK="SPECIAL_01234567890_TEST_STRING"

app_image_name="bozemanpass/test-progressive-web-app:stack"

# Without the config variable set, the app must not contain the test string.
# -m so that the check covers the resources the page pulls in, not just the page.
#
# The mirror is best-effort: the app references a robots.txt, an apple-icon and
# two favicons that it does not ship, so wget always ends with 404s and a
# non-zero status. The assertions below are the real check.
start_container -p 3000:80 -d -e STACK_SCRIPT_DEBUG=$STACK_SCRIPT_DEBUG ${app_image_name}
sleep 3
fetch_url http://localhost:3000 $scratch/test.before -m || true

docker logs $CONTAINER_ID
docker stop $CONTAINER_ID

# With it set, the app must pick it up at run time.
echo "Running app container test"
start_container -p 3000:80 -e CERC_WEBAPP_DEBUG=$CHECK -e STACK_SCRIPT_DEBUG=$STACK_SCRIPT_DEBUG -d ${app_image_name}
sleep 3
fetch_url http://localhost:3000 $scratch/test.after -m || true

docker logs $CONTAINER_ID
docker stop $CONTAINER_ID

echo "###########################################################################"
echo ""

# Assert the app was actually served before asserting the string is absent from
# it -- an empty download would satisfy the negative check for the wrong reason.
assert_file_contains $scratch/test.before "WEBAPP_DEBUG has value" APP-SERVED
assert_file_not_contains $scratch/test.before "$CHECK" BEFORE
assert_file_contains $scratch/test.after "$CHECK" AFTER

echo "Running deployment create test"
# Note: this is not a full test -- all we're testing here is that the webapp deploy command doesn't crash
test_deployment_dir=$STACK_TEST_DIR/test-deployment-dir
fake_k8s_config_file=$STACK_TEST_DIR/kube-config.yml
touch ${fake_k8s_config_file}

$TEST_TARGET_STACK webapp deploy --kube-config ${fake_k8s_config_file} --deployment-dir ${test_deployment_dir} --image ${app_image_name} --url https://my-test-app.example.com
if [ ! -d ${test_deployment_dir} ]; then
  fail "DEPLOY-CREATE: FAILED - deployment directory not present"
fi
echo "DEPLOY-CREATE: PASSED"

echo "Test passed"
