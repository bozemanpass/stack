#!/usr/bin/env bash
#
# Run tests against a real k3s cluster on a real cloud VM.
#
# Provisions a single-node k3s cluster (cluster.sh provision), runs each test
# script named on the command line against it with STACK_TEST_TARGET=remote, and
# destroys the VM on the way out:
#
#   ./tests/k3s-deploy/with-k3s-cluster.sh \
#       ./tests/app-deploy/run-test.sh ./tests/database/run-test.sh
#
# Unlike a kind-based run of those tests, this exercises the whole production
# arrangement: a remote kubeconfig, images pushed to and pulled from a real
# registry, DNS, and HTTPS with a real Let's Encrypt certificate obtained over
# ACME HTTP-01.
#
# The VM is destroyed (and its DNS record deleted) on exit, pass or fail.
#
# Provisioning the VM costs most of the wall-clock time and all of the money, so
# the tests share one: they run in sequence against the same cluster, each in
# its own namespace (a deployment's namespace is its compose project name), and
# a failure does not stop the ones after it -- the VM is already paid for, and
# the run may as well report every failure it can find. The exit status is
# non-zero if any test failed.
#
# Sequential, not parallel, and for two reasons: the deployments would contend
# for the single hostname's HTTP route, and each deployment that claims that
# hostname triggers a fresh Let's Encrypt issuance, where the duplicate
# certificate limit is 5 per week for an identical name set. Every run gets a
# fresh random hostname so runs do not interfere with each other, but that limit
# is the ceiling on how many HTTPS-serving tests one VM can carry. Tests with no
# HTTP endpoint (the database test) do not count against it.
#
# This is the whole lifecycle in one command, which is what a person at a
# terminal wants. CI drives cluster.sh directly instead, so that each test is a
# step of its own with its own status; see .github/workflows/test-deploy-k3s.yml.
# The requirements and the environment both commands read are documented there,
# in cluster.sh.
#
cluster_script="$( dirname -- "${BASH_SOURCE[0]}" )/cluster.sh"
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

if [ $# -eq 0 ]; then
  echo "Usage: $0 <test-script> [<test-script> ...]"
  echo "Runs each test script against a freshly provisioned k3s cluster."
  exit 1
fi

for test_script in "$@"; do
  if [ ! -x "$test_script" ]; then
    echo "Error: $test_script is not an executable file"
    exit 1
  fi
done

# Registered before provisioning, not after: a run interrupted midway through
# creating the VM has still created it.
cleanup () {
  rc=$?
  set +e
  "$cluster_script" destroy
  exit $rc
}
trap cleanup EXIT

# The tests run in this shell, so the cluster's settings have to reach it; under
# GitHub Actions cluster.sh publishes them to later steps instead.
state_dir=${STACK_K3S_STATE_DIR:-${RUNNER_TEMP:-${TMPDIR:-/tmp}}/stack-k3s-cluster}
"$cluster_script" provision
source "$state_dir/env.sh"

failed_tests=""
for test_script in "$@"; do
  echo "================================================================"
  echo "Running $test_script against $STACK_K8S_HOSTNAME"
  echo "================================================================"
  if "$test_script"; then
    echo "===== PASSED: $test_script"
  else
    echo "===== FAILED: $test_script"
    failed_tests="$failed_tests $test_script"
    "$cluster_script" diagnostics
  fi
done

if [ -n "$failed_tests" ]; then
  echo "Failed tests:$failed_tests"
  exit 1
fi
echo "All tests passed"
