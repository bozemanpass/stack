#!/usr/bin/env bash
#
# Run tests against Docker Compose on a real cloud machine.
#
# Provisions a VM with docker on it (machine.sh provision), uploads the test tree
# and the built package, runs each test script named on the command line on the
# machine with STACK_TEST_TARGET=remote-compose, and destroys the VM on the way
# out:
#
#   ./scripts/build_shiv_package.sh
#   ./tests/docker-deploy/with-docker-machine.sh ./tests/app-deploy/run-test.sh
#
# Unlike a local compose run of that test, this exercises the part of the Docker
# target that a laptop cannot: the docker-ingress stack terminating TLS for a real
# hostname in real public DNS, with a real Let's Encrypt certificate obtained over
# ACME HTTP-01.  Everything else about the target is covered locally, which is why
# this runs one test rather than the suite.
#
# The VM is destroyed (and its DNS record deleted) on exit, pass or fail.
#
# The tests run on the machine, not here, and they share it: provisioning is what
# costs, so a second test is nearly free.  They run in sequence, and a failure
# does not stop the ones after it -- the VM is already paid for, and the run may
# as well report every failure it can find.  The exit status is non-zero if any
# test failed.  Sequential rather than parallel because the deployments would
# contend for the machine's one hostname and its ports 80 and 443, and because
# each deployment claiming that hostname triggers a fresh certificate issuance.
#
# This is the whole lifecycle in one command, which is what a person at a terminal
# wants.  CI drives machine.sh directly instead, so that each test is a step of
# its own with its own status; see
# .github/workflows/test-deploy-remote-docker.yml.  The requirements and the
# environment both commands read are documented in machine.sh.
#
machine_script="$( dirname -- "${BASH_SOURCE[0]}" )/machine.sh"
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

if [ $# -eq 0 ]; then
  echo "Usage: $0 <test-script> [<test-script> ...]"
  echo "Runs each test script on a freshly provisioned docker machine."
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
  "$machine_script" destroy
  exit $rc
}
trap cleanup EXIT

"$machine_script" provision

# machine.sh run reports which tests failed and exits non-zero if any did; the
# diagnostics are worth the SSH round trip only in that case.
rc=0
"$machine_script" run "$@" || rc=$?
if [ $rc -ne 0 ]; then
  "$machine_script" diagnostics
  exit $rc
fi
echo "All tests passed"
