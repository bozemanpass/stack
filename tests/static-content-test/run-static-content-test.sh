#!/usr/bin/env bash
set -e

if [ -n "$STACK_SCRIPT_DEBUG" ]; then
  set -x
  echo "Environment variables:"
  env
fi

# Test hosting static content with the static-content wrapper
echo "Running stack static content test"
if [ "$1" == "from-path" ]; then
    TEST_TARGET_SO="stack"
else
    TEST_TARGET_SO=$( ls -t1 ./package/stack* | head -1 )
fi
# Set a non-default repo dir
STACK_TEST_DIR=~/stack-test/static-content-test-dir
export STACK_REPO_BASE_DIR=${STACK_TEST_DIR}/repo-base-dir
# Overridable for local testing against an unpushed content repo
TEST_CONTENT_REPO=${STACK_TEST_STATIC_CONTENT_REPO:-https://github.com/bozemanpass/stack-test-static-content.git}
echo "Testing this package: $TEST_TARGET_SO"
echo "Test version command"
reported_version_string=$( $TEST_TARGET_SO version )
echo "Version reported is: ${reported_version_string}"
echo "Cloning repositories into: $STACK_REPO_BASE_DIR"
rm -rf $STACK_TEST_DIR
mkdir -p $STACK_REPO_BASE_DIR
git clone $TEST_CONTENT_REPO $STACK_REPO_BASE_DIR/stack-test-static-content

# Test webapp command execution with the static-content wrapper
$TEST_TARGET_SO webapp build --wrapper static-content --source-repo $STACK_REPO_BASE_DIR/stack-test-static-content

set +e

app_image_name="bozemanpass/stack-test-static-content:stack"

CONTAINER_ID=$(docker run -p 3000:80 -d ${app_image_name})
if [ $? -ne 0 ]; then
  echo "Failed to start container from image ${app_image_name}"
  exit 1
fi
sleep 3
wget --tries 20 --retry-connrefused --waitretry=3 -O test.index http://localhost:3000/
wget -O test.subdir http://localhost:3000/pages/about.html
wget -O test.css http://localhost:3000/css/style.css
wget -O test.git http://localhost:3000/.git/config
git_rc=$?

docker logs $CONTAINER_ID
docker stop $CONTAINER_ID
if [ $? -ne 0 ]; then
  echo "Failed to stop container ${CONTAINER_ID}"
  exit 1
fi

echo "###########################################################################"
echo ""

grep "STACK_STATIC_CONTENT_TEST_INDEX_MARKER" test.index > /dev/null
if [ $? -ne 0 ]; then
  echo "INDEX: FAILED"
  exit 1
else
  echo "INDEX: PASSED"
fi

grep "STACK_STATIC_CONTENT_TEST_SUBDIR_MARKER" test.subdir > /dev/null
if [ $? -ne 0 ]; then
  echo "SUBDIR: FAILED"
  exit 1
else
  echo "SUBDIR: PASSED"
fi

grep "font-family" test.css > /dev/null
if [ $? -ne 0 ]; then
  echo "CSS: FAILED"
  exit 1
else
  echo "CSS: PASSED"
fi

# The .git directory must not be served
if [ $git_rc -eq 0 ]; then
  echo "GIT-NOT-SERVED: FAILED"
  exit 1
else
  echo "GIT-NOT-SERVED: PASSED"
fi

rm -f test.index test.subdir test.css test.git

set -e

# Test wrapping only a subdirectory of the source repo, with --content-root
subdir_image_name="bozemanpass/stack-test-static-content-content-root:stack"
$TEST_TARGET_SO webapp build --wrapper static-content \
  --source-repo $STACK_REPO_BASE_DIR/stack-test-static-content \
  --content-root pages \
  --tag ${subdir_image_name}

set +e

CONTAINER_ID=$(docker run -p 3000:80 -d ${subdir_image_name})
if [ $? -ne 0 ]; then
  echo "Failed to start container from image ${subdir_image_name}"
  exit 1
fi
sleep 3
# ./pages/about.html is the document root now ...
wget --tries 20 --retry-connrefused --waitretry=3 -O test.content-root http://localhost:3000/about.html
# ... and the content above it is not in the image at all.
wget -O test.content-root-index http://localhost:3000/index.html
index_rc=$?

docker stop $CONTAINER_ID > /dev/null

grep "STACK_STATIC_CONTENT_TEST_SUBDIR_MARKER" test.content-root > /dev/null
if [ $? -ne 0 ]; then
  echo "CONTENT-ROOT: FAILED"
  exit 1
else
  echo "CONTENT-ROOT: PASSED"
fi

if [ $index_rc -eq 0 ]; then
  echo "CONTENT-ROOT-NARROWED: FAILED"
  exit 1
else
  echo "CONTENT-ROOT-NARROWED: PASSED"
fi

rm -f test.content-root test.content-root-index

# Now test deploying static content as a stack component, via the wrapper field in stack.yml
echo "Running static content deployment test"

set -e

# Overridable for local testing against an unpushed stacks repo
if [ -n "$STACK_TEST_STACKS_REPO" ]; then
    git clone $STACK_TEST_STACKS_REPO $STACK_REPO_BASE_DIR/github.com/bozemanpass/stack-test-stacks
else
    $TEST_TARGET_SO fetch repo bozemanpass/stack-test-stacks
fi

$TEST_TARGET_SO prepare --stack test-static-content

# Deployment artifacts live outside the repo base dir, so the deployment's copy
# of the stack files is not seen when resolving stacks by name.
test_deployment_dir=$STACK_TEST_DIR/test-deployment-dir
test_deployment_spec=$STACK_TEST_DIR/test-deployment-spec.yml

$TEST_TARGET_SO init --stack test-static-content --output $test_deployment_spec --map-ports-to-host localhost-same
if [ ! -f "$test_deployment_spec" ]; then
    echo "DEPLOY-INIT: FAILED"
    exit 1
fi
echo "DEPLOY-INIT: PASSED"

$TEST_TARGET_SO deploy --spec-file $test_deployment_spec --deployment-dir $test_deployment_dir
if [ ! -d "$test_deployment_dir" ]; then
    echo "DEPLOY-CREATE: FAILED"
    exit 1
fi
echo "DEPLOY-CREATE: PASSED"

delete_cluster_exit () {
    $TEST_TARGET_SO manage --dir $test_deployment_dir stop --delete-volumes
    docker rm -f stack-test-registry > /dev/null 2>&1
}
trap delete_cluster_exit EXIT

$TEST_TARGET_SO manage --dir $test_deployment_dir start

set +e

wget --tries 20 --retry-connrefused --waitretry=3 -O test.deployed http://localhost:80/
grep "STACK_STATIC_CONTENT_TEST_INDEX_MARKER" test.deployed > /dev/null
if [ $? -ne 0 ]; then
  echo "DEPLOY-INDEX: FAILED"
  exit 1
else
  echo "DEPLOY-INDEX: PASSED"
fi

wget -O test.deployed-subdir http://localhost:80/pages/about.html
grep "STACK_STATIC_CONTENT_TEST_SUBDIR_MARKER" test.deployed-subdir > /dev/null
if [ $? -ne 0 ]; then
  echo "DEPLOY-SUBDIR: FAILED"
  exit 1
else
  echo "DEPLOY-SUBDIR: PASSED"
fi

rm -f test.deployed test.deployed-subdir

# Finally, build a stack whose container entry uses content-root in stack.yml.
set -e
$TEST_TARGET_SO build containers --stack test-static-content-subdir
set +e

stack_subdir_image_name="bozemanpass/stack-test-static-content-subdir:stack"
CONTAINER_ID=$(docker run -p 3001:80 -d ${stack_subdir_image_name})
if [ $? -ne 0 ]; then
  echo "Failed to start container from image ${stack_subdir_image_name}"
  exit 1
fi
sleep 3
wget --tries 20 --retry-connrefused --waitretry=3 -O test.stack-content-root http://localhost:3001/about.html

docker stop $CONTAINER_ID > /dev/null

grep "STACK_STATIC_CONTENT_TEST_SUBDIR_MARKER" test.stack-content-root > /dev/null
if [ $? -ne 0 ]; then
  echo "STACK-CONTENT-ROOT: FAILED"
  exit 1
else
  echo "STACK-CONTENT-ROOT: PASSED"
fi

rm -f test.stack-content-root

# Finally, test that a published prebuilt image is discovered and pulled rather
# than rebuilt.  Publish the wrapped image to a throwaway local registry, remove
# every local copy, then prepare again: the image's identity (the stack repo's
# commit hash, whose committed stack.lock pins the app source and wrapper) must
# match what was published, so it is fetched with no build.
echo "Running prebuilt image fetch test"

set -e

docker rm -f stack-test-registry > /dev/null 2>&1 || true
docker run -d --name stack-test-registry -p 5000:5000 registry:2

# The deployment holds a running container using the image, which would block
# image removal below; it has served its purpose, so stop it now.
$TEST_TARGET_SO manage --dir $test_deployment_dir stop --delete-volumes

static_content_stack_dir=$STACK_REPO_BASE_DIR/github.com/bozemanpass/stack-test-stacks/stack-files/stacks/test-static-content-stack

$TEST_TARGET_SO prepare --stack $static_content_stack_dir --publish-images --image-registry localhost:5000

# Remove every local tag of the app image so it can only come from the registry.
docker images bozemanpass/stack-test-static-content -q | sort -u | xargs -r docker rmi -f

$TEST_TARGET_SO prepare --stack $static_content_stack_dir --image-registry localhost:5000 | tee test.prepare-pull

set +e

grep -E "bozemanpass/stack-test-static-content +pulled" test.prepare-pull > /dev/null
if [ $? -ne 0 ]; then
  echo "PREBUILT-PULLED: FAILED"
  exit 1
else
  echo "PREBUILT-PULLED: PASSED"
fi

rm -f test.prepare-pull

exit 0
