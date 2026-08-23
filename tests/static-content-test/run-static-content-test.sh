#!/usr/bin/env bash
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

# Test hosting static content with the static-content wrapper
echo "Running stack static content test"
select_test_target "$@"
setup_test_dir static-content-test-dir
# Fetched pages are written here rather than the working directory, so a failed
# run does not leave test.* files scattered in the repo.
scratch=$STACK_TEST_DIR/fetched
mkdir -p $scratch
# Overridable for local testing against an unpushed content repo
TEST_CONTENT_REPO=${STACK_TEST_STATIC_CONTENT_REPO:-https://github.com/bozemanpass/stack-test-static-content.git}
echo "Cloning repositories into: $STACK_REPO_BASE_DIR"
git clone $TEST_CONTENT_REPO $STACK_REPO_BASE_DIR/stack-test-static-content

# Test webapp command execution with the static-content wrapper
$TEST_TARGET_STACK webapp build --wrapper static-content --source-repo $STACK_REPO_BASE_DIR/stack-test-static-content

app_image_name="bozemanpass/stack-test-static-content:stack"

# Nothing below configures authentication, so these are also this test's "no
# credentials configured" leg: what they assert is that the image serves its
# content to anyone until someone asks for a gate.  Shipping a gate that works
# only when it is configured, and quietly serves everything when it is not, is
# the failure they catch, so they are load-bearing rather than redundant with the
# authentication legs that follow.
start_container -p 3000:80 -d ${app_image_name}
sleep 3
fetch_url http://localhost:3000/ $scratch/test.index
fetch_url http://localhost:3000/pages/about.html $scratch/test.subdir
fetch_url http://localhost:3000/css/style.css $scratch/test.css
# The .git directory must not be served.  Asserted while the container is still
# up, or it would pass simply because nothing is listening.
assert_url_not_served http://localhost:3000/.git/config GIT-NOT-SERVED

docker logs $CONTAINER_ID
docker stop $CONTAINER_ID

echo "###########################################################################"
echo ""

assert_file_contains $scratch/test.index "STACK_STATIC_CONTENT_TEST_INDEX_MARKER" INDEX
assert_file_contains $scratch/test.subdir "STACK_STATIC_CONTENT_TEST_SUBDIR_MARKER" SUBDIR
assert_file_contains $scratch/test.css "font-family" CSS

# Now the same image with authentication configured.  The credentials are read
# from the environment when the container starts, so this is the same image the
# assertions above ran against, with nothing rebuilt.
echo "Running static content authentication test"

auth_user=alice
# Deliberately awkward: a password reaches the container as an argument, and the
# quoting is worth exercising once.
auth_password='s3cr#t pw'

start_container -p 3000:80 -d \
  -e STACK_AUTH_USER=${auth_user} \
  -e STACK_AUTH_PASSWORD="${auth_password}" \
  -e STACK_AUTH_REALM="Test Site" \
  -e STACK_AUTH_EXCLUDE=/css/ \
  ${app_image_name}

# The excluded path is served without credentials, so waiting for it is both the
# wait for the server to come up and the assertion that the exclusion works.
wait_for_content http://localhost:3000/css/style.css "font-family"
echo "AUTH-EXCLUDE: PASSED"

assert_url_status http://localhost:3000/ 401 AUTH-CHALLENGED
assert_url_status http://localhost:3000/pages/about.html 401 AUTH-CHALLENGED-SUBDIR
assert_url_status http://localhost:3000/ 401 AUTH-WRONG-PASSWORD -u "${auth_user}:wrong"
assert_url_status http://localhost:3000/ 401 AUTH-UNKNOWN-USER -u "nobody:${auth_password}"

curl -s -D $scratch/test.auth-headers -o /dev/null http://localhost:3000/
assert_file_contains $scratch/test.auth-headers 'WWW-Authenticate: Basic realm="Test Site"' AUTH-REALM

# The content itself, not just the status: a gate that answers 200 and serves
# nothing would pass every assertion above.
fetch_url http://localhost:3000/ $scratch/test.auth-index --user=${auth_user} --password="${auth_password}"
assert_file_contains $scratch/test.auth-index "STACK_STATIC_CONTENT_TEST_INDEX_MARKER" AUTH-SERVED

docker stop $CONTAINER_ID > /dev/null

# Several users, supplied already hashed.  The hashes are made with the image's
# own htpasswd, which is the tool the container would have used on a plaintext
# password anyway.
bob_entry=$( docker run --rm --entrypoint htpasswd ${app_image_name} -nbB bob bob-password )
carol_entry=$( docker run --rm --entrypoint htpasswd ${app_image_name} -nbB carol carol-password )

start_container -p 3000:80 -d -e STACK_AUTH_HTPASSWD="${bob_entry}
${carol_entry}" ${app_image_name}

fetch_url http://localhost:3000/ $scratch/test.auth-htpasswd --user=bob --password=bob-password
assert_file_contains $scratch/test.auth-htpasswd "STACK_STATIC_CONTENT_TEST_INDEX_MARKER" AUTH-HTPASSWD
assert_url_status http://localhost:3000/ 200 AUTH-HTPASSWD-SECOND-USER -u carol:carol-password
assert_url_status http://localhost:3000/ 401 AUTH-HTPASSWD-CHALLENGED

docker stop $CONTAINER_ID > /dev/null

# Half a credential must fail the container's start rather than resolve itself
# one way or the other: taking the user alone would serve the content to anyone,
# and taking the password alone would lock it behind a name nobody knows.  No
# published port here -- the container is expected to exit.
if docker run --rm -e STACK_AUTH_USER=${auth_user} ${app_image_name} > /dev/null 2>&1; then
    fail "AUTH-HALF-CREDENTIAL: FAILED - the container started with a user and no password"
fi
echo "AUTH-HALF-CREDENTIAL: PASSED"

# Test wrapping only a subdirectory of the source repo, with --content-root
subdir_image_name="bozemanpass/stack-test-static-content-content-root:stack"
$TEST_TARGET_STACK webapp build --wrapper static-content \
  --source-repo $STACK_REPO_BASE_DIR/stack-test-static-content \
  --content-root pages \
  --tag ${subdir_image_name}

start_container -p 3000:80 -d ${subdir_image_name}
sleep 3
# ./pages/about.html is the document root now ...
fetch_url http://localhost:3000/about.html $scratch/test.content-root
# ... and the content above it is not in the image at all.
assert_url_not_served http://localhost:3000/index.html CONTENT-ROOT-NARROWED

docker stop $CONTAINER_ID > /dev/null

assert_file_contains $scratch/test.content-root "STACK_STATIC_CONTENT_TEST_SUBDIR_MARKER" CONTENT-ROOT

# Now test deploying static content as a stack component, via the wrapper field in stack.yml
echo "Running static content deployment test"

# Overridable for local testing against an unpushed stacks repo
if [ -n "$STACK_TEST_STACKS_REPO" ]; then
    git clone $STACK_TEST_STACKS_REPO $STACK_REPO_BASE_DIR/github.com/bozemanpass/stack-test-stacks
else
    $TEST_TARGET_STACK fetch repo bozemanpass/stack-test-stacks
fi

$TEST_TARGET_STACK prepare --stack test-static-content

# Deployment artifacts live outside the repo base dir, so the deployment's copy
# of the stack files is not seen when resolving stacks by name.
test_deployment_dir=$STACK_TEST_DIR/test-deployment-dir
test_deployment_spec=$STACK_TEST_DIR/test-deployment-spec.yml

$TEST_TARGET_STACK init --stack test-static-content --output $test_deployment_spec --map-ports-to-host localhost-same
if [ ! -f "$test_deployment_spec" ]; then
    fail "DEPLOY-INIT: FAILED - spec file not present"
fi
echo "DEPLOY-INIT: PASSED"

# Teardown: the shared handler stops the deployment, and the scratch registry
# started later on is this test's own to clean up.
remove_test_registry () {
    docker rm -f stack-test-registry > /dev/null 2>&1 || true
}
TEST_EXTRA_CLEANUP=remove_test_registry
stop_deployment_on_exit $test_deployment_dir

$TEST_TARGET_STACK deploy --spec-file $test_deployment_spec --deployment-dir $test_deployment_dir
if [ ! -d "$test_deployment_dir" ]; then
    fail "DEPLOY-CREATE: FAILED - deployment directory not present"
fi
echo "DEPLOY-CREATE: PASSED"

$TEST_TARGET_STACK manage --dir $test_deployment_dir start

fetch_url http://localhost:80/ $scratch/test.deployed
assert_file_contains $scratch/test.deployed "STACK_STATIC_CONTENT_TEST_INDEX_MARKER" DEPLOY-INDEX

fetch_url http://localhost:80/pages/about.html $scratch/test.deployed-subdir
assert_file_contains $scratch/test.deployed-subdir "STACK_STATIC_CONTENT_TEST_SUBDIR_MARKER" DEPLOY-SUBDIR

# Turning authentication on after the deployment exists, which is the case worth
# testing: a site is normally published before anyone decides it should be
# private.  A deployment's config lives in config.env, and `update` is what
# applies a change to it -- no rebuild, and the same image is left running.
echo "Running post-deployment authentication test"

deployed_password=deployed-secret
cat >> $test_deployment_dir/config.env <<EOF
STACK_AUTH_USER=${auth_user}
STACK_AUTH_PASSWORD=${deployed_password}
EOF

$TEST_TARGET_STACK manage --dir $test_deployment_dir update

# The authenticated fetch first: wget retries while the recreated container comes
# up, so it doubles as the wait, and an immediate status assertion here would
# otherwise read a refused connection as a gated site.
fetch_url http://localhost:80/ $scratch/test.deployed-auth --user=${auth_user} --password=${deployed_password}
assert_file_contains $scratch/test.deployed-auth "STACK_STATIC_CONTENT_TEST_INDEX_MARKER" DEPLOY-AUTH-SERVED
assert_url_status http://localhost:80/ 401 DEPLOY-AUTH-CHALLENGED

# And off again: the same edit in reverse ungates the site, which is the half of
# the claim that a test of turning it on does not make.
grep -v '^STACK_AUTH_' $test_deployment_dir/config.env > $test_deployment_dir/config.env.ungated
mv $test_deployment_dir/config.env.ungated $test_deployment_dir/config.env

$TEST_TARGET_STACK manage --dir $test_deployment_dir update

fetch_url http://localhost:80/ $scratch/test.deployed-ungated
assert_file_contains $scratch/test.deployed-ungated "STACK_STATIC_CONTENT_TEST_INDEX_MARKER" DEPLOY-AUTH-REMOVED

# Finally, build a stack whose container entry uses content-root in stack.yml.
$TEST_TARGET_STACK build containers --stack test-static-content-subdir

stack_subdir_image_name="bozemanpass/stack-test-static-content-subdir:stack"
start_container -p 3001:80 -d ${stack_subdir_image_name}
sleep 3
fetch_url http://localhost:3001/about.html $scratch/test.stack-content-root

docker stop $CONTAINER_ID > /dev/null

assert_file_contains $scratch/test.stack-content-root "STACK_STATIC_CONTENT_TEST_SUBDIR_MARKER" STACK-CONTENT-ROOT

# Finally, test that a published prebuilt image is discovered and pulled rather
# than rebuilt.  Publish the wrapped image to a throwaway local registry, remove
# every local copy, then prepare again: the image's identity (the stack repo's
# commit hash, whose committed stack.lock pins the app source and wrapper) must
# match what was published, so it is fetched with no build.
echo "Running prebuilt image fetch test"

docker rm -f stack-test-registry > /dev/null 2>&1 || true
docker run -d --name stack-test-registry -p 5000:5000 registry:2

# The deployment holds a running container using the image, which would block
# image removal below; it has served its purpose, so stop it now.
$TEST_TARGET_STACK manage --dir $test_deployment_dir destroy --yes

static_content_stack_dir=$STACK_REPO_BASE_DIR/github.com/bozemanpass/stack-test-stacks/stack-files/stacks/test-static-content-stack

$TEST_TARGET_STACK prepare --stack $static_content_stack_dir --publish-images --image-registry localhost:5000

# Remove every local tag of the app image so it can only come from the registry.
docker images bozemanpass/stack-test-static-content -q | sort -u | xargs -r docker rmi -f

$TEST_TARGET_STACK prepare --stack $static_content_stack_dir --image-registry localhost:5000 | tee $scratch/test.prepare-pull

assert_file_contains $scratch/test.prepare-pull "bozemanpass/stack-test-static-content +pulled" PREBUILT-PULLED

echo "Test passed"
