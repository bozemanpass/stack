#!/usr/bin/env bash
set -e

if [ -n "$STACK_SCRIPT_DEBUG" ]; then
  set -x
fi

# Dump environment variables for debugging
echo "Environment variables:"
env
# Test hosting static content with the static-content wrapper
echo "Running stack static content test"
if [ "$1" == "from-path" ]; then
    TEST_TARGET_SO="stack"
else
    TEST_TARGET_SO=$( ls -t1 ./package/stack* | head -1 )
fi
# Set a non-default repo dir
export STACK_REPO_BASE_DIR=~/stack-test/static-content-repo-base-dir
# Overridable for local testing against an unpushed content repo
TEST_CONTENT_REPO=${STACK_TEST_STATIC_CONTENT_REPO:-https://github.com/bozemanpass/stack-test-static-content.git}
echo "Testing this package: $TEST_TARGET_SO"
echo "Test version command"
reported_version_string=$( $TEST_TARGET_SO version )
echo "Version reported is: ${reported_version_string}"
echo "Cloning repositories into: $STACK_REPO_BASE_DIR"
rm -rf $STACK_REPO_BASE_DIR
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

exit 0
