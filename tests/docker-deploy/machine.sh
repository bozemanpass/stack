#!/usr/bin/env bash
#
# The remote Docker test machine's lifecycle, as separately addressable commands:
#
#   machine.sh provision     create the VM, wait for docker, upload the test tree
#   machine.sh sync          upload the test tree again, without a new VM
#   machine.sh run <script>  run a test script on the VM
#   machine.sh diagnostics   dump machine state, for a test that has just failed
#   machine.sh destroy       delete the VM and its DNS record
#
# This is tests/k3s-deploy/cluster.sh for the Docker target, and the reason it is
# a second script rather than a mode of that one is the "run" command above.  A
# remote *cluster* is driven over its API, so there the tests run on the runner
# and provisioning only has to hand them a kubeconfig; Docker has no equivalent,
# and the compose deployer writes the deployment's files and bind-mounts its
# volume directories on the machine the daemon is on.  So here the test itself
# runs on the VM, over SSH, and what provisioning hands it is a copy of the tree
# it runs from.
#
# That is also why nothing is published to GITHUB_ENV, unlike the cluster script:
# no later step needs the machine's settings, because no later step talks to it
# except through "run".  What has to survive between commands is the machine's id
# and FQDN, and those are kept in a state directory (STACK_DOCKER_STATE_DIR, by
# default under RUNNER_TEMP or TMPDIR).  The id is written the moment it is known:
# a run that dies between create and destroy leaves a VM behind, and the id is
# what makes it findable.
#
# What this covers that a local compose test cannot is TLS: a real hostname in
# real public DNS, ports 80 and 443 reachable from the internet, and a real Let's
# Encrypt certificate obtained over ACME HTTP-01 by the docker-ingress stack.
# Everything else about the Docker target is testable on a laptop, so only the
# app deploy test runs here -- see .github/workflows/test-deploy-remote-docker.yml.
#
# The images are built on the VM.  There is no remote deploy for Docker to push
# them from anywhere else, and no registry in the arrangement at all: the test
# fetches the app's repository on the machine and builds there, which works
# because the example app's repository is public.
#
# tests/docker-deploy/with-docker-machine.sh is this same lifecycle for a human
# at a terminal -- provision, run the named tests, destroy on the way out -- and
# is implemented in terms of these commands.
#
# Requires: machine (https://github.com/stirlingbridge/machine), jq, ssh, tar.
# The SSH key named by MACHINE_SSH_KEY_NAME must be registered with the cloud
# provider, and MACHINE_SSH_KEY_FILE must be the matching private key.
#
# Required environment (provision only):
#   MACHINE_DO_TOKEN         DigitalOcean API token
#   MACHINE_SSH_KEY_NAME     Name of an SSH key registered at the provider
#   MACHINE_SSH_KEY_FILE     Path to the matching private key file
#   MACHINE_DNS_ZONE         DNS zone hosted at the provider; the test hostname
#                            is a machine-unique name under this zone
#   LETSENCRYPT_EMAIL        Let's Encrypt contact address, passed to the test as
#                            the address the certificate is registered to
#
# Optional environment:
#   STACK_DOCKER_STATE_DIR   Where the machine's id and FQDN are kept between
#                            commands
#   STACK_TEST_ACME_CA_URI   Passed through to the test, which uses Let's
#                            Encrypt production by default (see
#                            init_ingress_mix_in in ../lib/common.sh)
#   MACHINE_REGION           Provider region (default nyc3)
#   MACHINE_SIZE             Machine size slug (default s-2vcpu-4gb)
#   MACHINE_IMAGE            Machine image (default ubuntu-24-04-x64)
#   MACHINE_PROJECT          DigitalOcean project to assign the VM to
#   MACHINE_PROVISIONING_URL URL of combine.sh; sibling scripts are fetched
#                            relative to it, so pointing this at a branch of
#                            machine-provisioning tests that branch
#                            (default: the main branch)
#   MACHINE_CMD              The machine command to run (default: machine)
#
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

MACHINE_CMD=${MACHINE_CMD:-machine}
MACHINE_REGION=${MACHINE_REGION:-nyc3}
MACHINE_SIZE=${MACHINE_SIZE:-s-2vcpu-4gb}
MACHINE_IMAGE=${MACHINE_IMAGE:-ubuntu-24-04-x64}
MACHINE_PROVISIONING_URL=${MACHINE_PROVISIONING_URL:-https://raw.githubusercontent.com/stirlingbridge/machine-provisioning/refs/heads/main/scripts/combine.sh}
STACK_DOCKER_STATE_DIR=${STACK_DOCKER_STATE_DIR:-${RUNNER_TEMP:-${TMPDIR:-/tmp}}/stack-docker-machine}
MACHINE_NEW_USER=stacktest

# How long to allow for the VM to boot and cloud-init to install docker
# (seconds).  Much less than a cluster needs, which is most of what makes this
# test cheaper than the k3s one.
PROVISION_TIMEOUT=900

# Where on the VM the test tree is copied to, and what is copied: the test
# scripts and the package they test, which is all a test script reads from the
# repository.  Deliberately not the whole repository -- the source is not what is
# under test here, the built package is.
REMOTE_WORK_DIR="stack-under-test"
UPLOAD_PATHS=(tests package)

machine_config=$STACK_DOCKER_STATE_DIR/config.yml
machine_id_file=$STACK_DOCKER_STATE_DIR/machine-id
fqdn_file=$STACK_DOCKER_STATE_DIR/fqdn
known_hosts=$STACK_DOCKER_STATE_DIR/known_hosts

machine_ssh () {
    ssh -i "$MACHINE_SSH_KEY_FILE" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$known_hosts" \
        "${MACHINE_NEW_USER}@$( cat "$fqdn_file" )" "$@"
}

require_machine () {
    if [ ! -f "$fqdn_file" ]; then
        fail "Error: no machine has been provisioned (state directory: $STACK_DOCKER_STATE_DIR)"
    fi
}

# Copy the test tree to the VM, replacing whatever is there.  Sent as a tar
# stream rather than with scp so that the transfer is one SSH connection and the
# remote side needs nothing installed for it.
#
# A command of its own as well as part of provisioning: a VM is the expensive
# part of a run, and re-uploading a fixed test to the one already running beats
# paying for another.
sync_source () {
    require_machine
    require_commands tar
    local path
    for path in "${UPLOAD_PATHS[@]}"; do
        if [ ! -d "$path" ]; then
            fail "Error: $path not found; run this from the repo root, and build the package first"
        fi
    done
    if [ -z "$( ls -A ./package )" ]; then
        fail "Error: ./package is empty; run ./scripts/build_shiv_package.sh first"
    fi
    echo "Uploading ${UPLOAD_PATHS[*]} to ${REMOTE_WORK_DIR} on $( cat "$fqdn_file" )"
    tar czf - "${UPLOAD_PATHS[@]}" \
        | machine_ssh "rm -rf ${REMOTE_WORK_DIR} && mkdir -p ${REMOTE_WORK_DIR} && tar xzf - -C ${REMOTE_WORK_DIR}"
}

provision () {
    require_commands "$MACHINE_CMD" jq ssh tar

    local missing=""
    local var
    for var in MACHINE_DO_TOKEN MACHINE_SSH_KEY_NAME MACHINE_SSH_KEY_FILE MACHINE_DNS_ZONE LETSENCRYPT_EMAIL; do
        if [ -z "${!var}" ]; then
            missing="$missing $var"
        fi
    done
    if [ -n "$missing" ]; then
        fail "Error: required environment not set:$missing"
    fi

    if [ ! -f "$MACHINE_SSH_KEY_FILE" ]; then
        fail "Error: MACHINE_SSH_KEY_FILE $MACHINE_SSH_KEY_FILE does not exist"
    fi

    # A machine left over from an earlier provision would be leaked by this one,
    # since the id file is the only record of it.
    if [ -f "$machine_id_file" ]; then
        fail "Error: $machine_id_file already exists; destroy that machine first"
    fi
    # The config file below holds the provider token, so the directory it lands
    # in is the caller's alone.
    mkdir -p "$STACK_DOCKER_STATE_DIR"
    chmod 700 "$STACK_DOCKER_STATE_DIR"

    # A machine-unique name gives a unique FQDN, which keeps runs independent and
    # avoids Let's Encrypt duplicate-certificate rate limits.
    local machine_name="stackdocker-$(head -c4 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    local machine_fqdn="${machine_name}.${MACHINE_DNS_ZONE}"
    echo "$machine_fqdn" > "$fqdn_file"

    # health.sh serves the status endpoint that "machine status" polls; fqdn.sh
    # records the machine's own name for anything on it that needs it; docker.sh
    # installs the engine.  The packages come last because they include docker's
    # own compose and buildx plugins, which are in the apt repository docker.sh
    # adds -- they arrive as recommends of docker-ce, and naming them is how this
    # stops depending on that.  jq, wget and git are what the test scripts use.
    cat > "$machine_config" <<EOF
digital-ocean:
    access-token: ${MACHINE_DO_TOKEN}
    ssh-key: ${MACHINE_SSH_KEY_NAME}
    dns-zone: ${MACHINE_DNS_ZONE}
    machine-size: ${MACHINE_SIZE}
    image: ${MACHINE_IMAGE}
    region: ${MACHINE_REGION}
EOF
    if [ -n "$MACHINE_PROJECT" ]; then
        echo "    project: ${MACHINE_PROJECT}" >> "$machine_config"
    fi
    cat >> "$machine_config" <<EOF
machines:
    docker-stack-host:
        new-user-name: ${MACHINE_NEW_USER}
        script-dir: /opt/stacktest
        script-url: ${MACHINE_PROVISIONING_URL}
        script-path: /opt/stacktest/combine.sh
        script-args:
          - health.sh
          - fqdn.sh
          - docker.sh
          - packages.sh jq wget git docker-compose-plugin docker-buildx-plugin
EOF

    echo "Creating machine $machine_fqdn"
    $MACHINE_CMD --config-file "$machine_config" create --name "$machine_name" --type docker-stack-host --wait-for-ip

    local machine_id
    machine_id=$($MACHINE_CMD --config-file "$machine_config" list --name "$machine_name" --output json | jq -r '.[0].id')
    if [ -z "$machine_id" ] || [ "$machine_id" == "null" ]; then
        fail "Error: could not determine the id of the created machine"
    fi
    # Written before anything else can fail: from here on destroy can find it.
    echo "$machine_id" > "$machine_id_file"
    echo "Machine created with id $machine_id"

    echo "Waiting for provisioning to complete (up to ${PROVISION_TIMEOUT}s)..."
    local start_time=$SECONDS
    local provision_status="UNKNOWN"
    local reported_status=""
    while [ $((SECONDS - start_time)) -lt $PROVISION_TIMEOUT ]; do
        provision_status=$($MACHINE_CMD --config-file "$machine_config" status --id "$machine_id" --output json \
            | jq -r '.[0]["cloud-init-status"]')
        # Only when it changes: this polls every 15 seconds, and a line per poll
        # would bury the run's actual output.  Silence for the whole wait is worse
        # though -- a machine whose status endpoint never answers looks exactly
        # like one that is still working.
        if [ "$provision_status" != "$reported_status" ]; then
            echo "  provisioning status: $provision_status ($((SECONDS - start_time))s)"
            reported_status="$provision_status"
        fi
        case "$provision_status" in
            UP)
                break
                ;;
            ERROR)
                echo "Provisioning failed; fetching the cloud-init log:"
                machine_ssh "sudo tail -100 /var/log/cloud-init-output.log" || true
                fail "Error: provisioning failed"
                ;;
            *)
                sleep 15
                ;;
        esac
    done
    if [ "$provision_status" != "UP" ]; then
        # The same log the ERROR branch fetches, and for the same reason: the
        # machine is about to be destroyed by whatever wrapped this, and the log
        # is the only account of what it was doing.  A timeout has one extra
        # suspect that an ERROR does not -- the status endpoint itself, which is
        # what "UNKNOWN" means -- so report whether SSH works at all, since a
        # machine that answers this answers on the network but not on port 4242.
        echo "Provisioning did not complete; fetching the cloud-init log:"
        machine_ssh "cloud-init status; sudo tail -100 /var/log/cloud-init-output.log" \
            || echo "(the machine could not be reached over SSH either)"
        fail "Error: timed out waiting for provisioning to complete (last status: $provision_status)"
    fi
    echo "Provisioning complete"

    # The test hostname has to resolve before the HTTP checks can pass, and here
    # it is the machine itself that resolves it -- the test runs there and reaches
    # the app by its public name.  The authoritative record was just created; the
    # CA resolves it independently.
    echo "Waiting for $machine_fqdn to resolve on the machine..."
    local resolved=""
    for _ in {1..60}; do
        if machine_ssh "getent hosts $machine_fqdn" > /dev/null 2>&1; then
            resolved=yes
            break
        fi
        sleep 5
    done
    if [ -z "$resolved" ]; then
        fail "Error: $machine_fqdn does not resolve on the machine"
    fi

    # That the engine and its compose plugin are really there, checked here rather
    # than discovered as a confusing failure inside a test.  What the machine ended
    # up with is worth recording on every run in any case: the provisioning
    # installs current versions, so "which docker did that run test?" is otherwise
    # unanswerable once the VM is gone.
    if ! machine_ssh "docker version && docker compose version && python3 --version" ; then
        fail "Error: the machine does not have a working docker with the compose plugin"
    fi

    sync_source
    echo "Machine ready at $machine_fqdn"
}

# Run test scripts on the machine, in sequence, and report which failed.  Each is
# a path in the repository, as it would be run locally:
#
#     machine.sh run ./tests/app-deploy/run-test.sh
#
# The environment the test needs is passed explicitly on the command line: an
# SSH session inherits nothing from here, and the test reads the target and the
# hostname through select_deploy_target.
run () {
    require_machine
    if [ $# -eq 0 ]; then
        fail "Usage: $0 run <test-script> [<test-script> ...]"
    fi
    local machine_fqdn
    machine_fqdn=$( cat "$fqdn_file" )

    local remote_env
    remote_env="STACK_TEST_TARGET=remote-compose"
    remote_env="$remote_env STACK_COMPOSE_HOSTNAME=$( printf '%q' "$machine_fqdn" )"
    remote_env="$remote_env LETSENCRYPT_EMAIL=$( printf '%q' "$LETSENCRYPT_EMAIL" )"
    if [ -n "$STACK_TEST_ACME_CA_URI" ]; then
        remote_env="$remote_env STACK_TEST_ACME_CA_URI=$( printf '%q' "$STACK_TEST_ACME_CA_URI" )"
    fi
    if [ -n "$STACK_SCRIPT_DEBUG" ]; then
        remote_env="$remote_env STACK_SCRIPT_DEBUG=$( printf '%q' "$STACK_SCRIPT_DEBUG" )"
    fi

    local failed=""
    local script
    for script in "$@"; do
        echo "================================================================"
        echo "Running $script on $machine_fqdn"
        echo "================================================================"
        if machine_ssh "cd ${REMOTE_WORK_DIR} && ${remote_env} $( printf '%q' "$script" )"; then
            echo "===== PASSED: $script"
        else
            echo "===== FAILED: $script"
            failed="$failed $script"
        fi
    done
    if [ -n "$failed" ]; then
        fail "Failed tests:$failed"
    fi
}

# The machine is destroyed when the run ends, so its state has to be captured
# while the failure is fresh -- afterwards there is nothing left to look at.
#
# The deployment's own containers and their logs are not here: a test tears its
# deployment down on the way out, dumping those logs first (dump_diagnostics in
# ../lib/common.sh), and that dump includes the ingress containers because the
# proxy is mixed into the same deployment.  What is left for this to answer is
# whether the machine itself was in the state the test assumed.
diagnostics () {
    if [ ! -f "$fqdn_file" ]; then
        echo "No machine to collect diagnostics from"
        return
    fi
    echo "----- machine diagnostics -----"
    machine_ssh \
        "docker ps -a; \
         docker image ls; \
         docker volume ls; \
         df -h /; \
         free -m; \
         sudo tail -50 /var/log/cloud-init-output.log" || true
}

# Destroying is safe to call when there is nothing to destroy: it is wired to run
# however a run ends, including ones that failed before creating anything.
destroy () {
    if [ ! -f "$machine_id_file" ]; then
        echo "No machine to destroy"
        rm -rf "$STACK_DOCKER_STATE_DIR"
        return
    fi
    local machine_id
    machine_id=$( cat "$machine_id_file" )
    echo "Destroying machine $( cat "$fqdn_file" ) ($machine_id)"
    $MACHINE_CMD --config-file "$machine_config" destroy --no-confirm --delete-dns "$machine_id"
    # Only once the provider has confirmed it: the state directory is the record
    # of a machine that still exists, and holds the token needed to remove it.
    rm -rf "$STACK_DOCKER_STATE_DIR"
}

command=${1:-}
shift || true
case "$command" in
    provision)   provision ;;
    sync)        sync_source ;;
    run)         run "$@" ;;
    diagnostics) diagnostics ;;
    destroy)     destroy ;;
    *)
        echo "Usage: $0 provision|sync|run <test-script>...|diagnostics|destroy"
        echo "See with-docker-machine.sh for the whole lifecycle in one command"
        exit 1
        ;;
esac
