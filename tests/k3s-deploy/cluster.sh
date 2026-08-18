#!/usr/bin/env bash
#
# The k3s test cluster's lifecycle, as separately addressable commands:
#
#   cluster.sh provision     create the VM, wait for k3s, write the connection settings
#   cluster.sh diagnostics   dump cluster state, for a test that has just failed
#   cluster.sh destroy       delete the VM and its DNS record
#
# Provisioning costs money and most of the wall-clock time, so several tests share
# one cluster.  That used to mean one script that provisioned, ran every test in a
# loop, and destroyed -- which made the whole run a single GitHub Actions step:
# one pass/fail covering four tests, with which one failed discoverable only by
# reading the log and knowing what each test does.  Splitting the lifecycle out is
# what lets each test be an ordinary step, with its own name and its own status,
# while the cluster goes on living between them.
#
# The settings the tests need are written to a state directory that outlives each
# command (STACK_K3S_STATE_DIR, by default under RUNNER_TEMP or TMPDIR), as a
# shell fragment to source; under GitHub Actions they are appended to GITHUB_ENV
# as well, so later steps inherit them without sourcing anything.  The same
# directory carries what destroy needs, which is why the machine's id is written
# there the moment it is known: a run that dies between create and destroy leaves
# a VM behind, and the id is what makes it findable.
#
# tests/k3s-deploy/with-k3s-cluster.sh is this same lifecycle for a human at a
# terminal -- provision, run the named tests, destroy on the way out -- and is
# implemented in terms of these commands.
#
# Requires: machine (https://github.com/stirlingbridge/machine), docker, jq, ssh.
# The SSH key named by MACHINE_SSH_KEY_NAME must be registered with the cloud
# provider, and MACHINE_SSH_KEY_FILE must be the matching private key -- it is
# used to fetch the cluster's kubeconfig from the VM.
#
# Required environment (provision only):
#   MACHINE_DO_TOKEN         DigitalOcean API token
#   MACHINE_SSH_KEY_NAME     Name of an SSH key registered at the provider
#   MACHINE_SSH_KEY_FILE     Path to the matching private key file
#   MACHINE_DNS_ZONE         DNS zone hosted at the provider; the test hostname
#                            is a machine-unique name under this zone
#   STACK_IMAGE_REGISTRY     Registry to push the stack's images to and for the
#                            cluster to pull them from, including any org path
#                            (e.g. registry.digitalocean.com/myorg)
#   STACK_IMAGE_REGISTRY_USER
#   STACK_IMAGE_REGISTRY_TOKEN
#                            Credentials for that registry (for a DigitalOcean
#                            registry, pass the API token as both)
#   LETSENCRYPT_EMAIL        Let's Encrypt contact address
#
# Optional environment:
#   STACK_K3S_MODE           "gateway" (default) provisions the Gateway API
#                            arrangement, which is k3s-node.sh's own default;
#                            "ingress" provisions the legacy nginx arrangement
#                            (k3s-node.sh --nginx-ingress)
#   STACK_K3S_STATE_DIR      Where the settings and the machine id are kept
#                            between commands
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
# The backup tests need object store settings of their own; they are read by the
# tests themselves (select_backup_target in ../lib/common.sh) and nothing here
# looks at them.
#
source "$( dirname -- "${BASH_SOURCE[0]}" )/../lib/common.sh"

MACHINE_CMD=${MACHINE_CMD:-machine}
MACHINE_REGION=${MACHINE_REGION:-nyc3}
MACHINE_SIZE=${MACHINE_SIZE:-s-2vcpu-4gb}
MACHINE_IMAGE=${MACHINE_IMAGE:-ubuntu-24-04-x64}
MACHINE_PROVISIONING_URL=${MACHINE_PROVISIONING_URL:-https://raw.githubusercontent.com/stirlingbridge/machine-provisioning/refs/heads/main/scripts/combine.sh}
STACK_K3S_MODE=${STACK_K3S_MODE:-gateway}
STACK_K3S_STATE_DIR=${STACK_K3S_STATE_DIR:-${RUNNER_TEMP:-${TMPDIR:-/tmp}}/stack-k3s-cluster}
MACHINE_NEW_USER=stacktest

# How long to allow for the VM to boot and cloud-init to install k3s,
# cert-manager etc. (seconds).
PROVISION_TIMEOUT=1800

machine_config=$STACK_K3S_STATE_DIR/config.yml
machine_id_file=$STACK_K3S_STATE_DIR/machine-id
fqdn_file=$STACK_K3S_STATE_DIR/fqdn
kube_config=$STACK_K3S_STATE_DIR/kubeconfig
known_hosts=$STACK_K3S_STATE_DIR/known_hosts
env_file=$STACK_K3S_STATE_DIR/env.sh

# Run a command on the VM as root.  Every use is diagnostic or read-only: the
# provisioning itself happens in cloud-init.
cluster_ssh () {
    ssh -i "$MACHINE_SSH_KEY_FILE" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$known_hosts" \
        "${MACHINE_NEW_USER}@$( cat "$fqdn_file" )" "$@"
}

# Make $1=$2 visible to whatever runs next: to a shell that sources env.sh, and
# under GitHub Actions to the later steps of the job.
publish_setting () {
    echo "export $1=\"$2\"" >> "$env_file"
    if [ -n "$GITHUB_ENV" ]; then
        echo "$1=$2" >> "$GITHUB_ENV"
    fi
}

provision () {
    require_commands "$MACHINE_CMD" jq ssh docker

    local missing=""
    local var
    for var in MACHINE_DO_TOKEN MACHINE_SSH_KEY_NAME MACHINE_SSH_KEY_FILE MACHINE_DNS_ZONE \
               STACK_IMAGE_REGISTRY STACK_IMAGE_REGISTRY_USER STACK_IMAGE_REGISTRY_TOKEN LETSENCRYPT_EMAIL; do
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

    local k3s_mode_args
    case "$STACK_K3S_MODE" in
        gateway)
            k3s_mode_args=""
            ;;
        ingress)
            k3s_mode_args="--nginx-ingress"
            ;;
        *)
            fail "Error: STACK_K3S_MODE must be gateway or ingress, not $STACK_K3S_MODE"
            ;;
    esac

    # A cluster left over from an earlier provision would be leaked by this one,
    # since the id file is the only record of it.
    if [ -f "$machine_id_file" ]; then
        fail "Error: $machine_id_file already exists; destroy that cluster first"
    fi
    # The config file below holds the provider token, so the directory it lands
    # in is the caller's alone.
    mkdir -p "$STACK_K3S_STATE_DIR"
    chmod 700 "$STACK_K3S_STATE_DIR"
    : > "$env_file"

    # A machine-unique name gives a unique FQDN, which keeps runs independent and
    # avoids Let's Encrypt duplicate-certificate rate limits.
    local machine_name="stackk3s-$(head -c4 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    local machine_fqdn="${machine_name}.${MACHINE_DNS_ZONE}"
    echo "$machine_fqdn" > "$fqdn_file"

    # The registry credentials in script-args end up in the VM's cloud-init user
    # data; use a registry and credentials dedicated to testing.
    # health.sh serves the status endpoint that "machine status" polls; k3s-node.sh
    # needs the registry credentials so that the cluster can pull the test images.
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
    k8s-stack-host:
        new-user-name: ${MACHINE_NEW_USER}
        script-dir: /opt/stacktest
        script-url: ${MACHINE_PROVISIONING_URL}
        script-path: /opt/stacktest/combine.sh
        script-args:
          - health.sh
          - fqdn.sh
          - k3s-node.sh -y ${k3s_mode_args} --letsencrypt-email ${LETSENCRYPT_EMAIL} --image-registry ${STACK_IMAGE_REGISTRY} --image-registry-username ${STACK_IMAGE_REGISTRY_USER} --image-registry-password ${STACK_IMAGE_REGISTRY_TOKEN}
EOF

    echo "Creating machine $machine_fqdn (mode: $STACK_K3S_MODE)"
    $MACHINE_CMD --config-file "$machine_config" create --name "$machine_name" --type k8s-stack-host --wait-for-ip

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
    while [ $((SECONDS - start_time)) -lt $PROVISION_TIMEOUT ]; do
        provision_status=$($MACHINE_CMD --config-file "$machine_config" status --id "$machine_id" --output json \
            | jq -r '.[0]["cloud-init-status"]')
        case "$provision_status" in
            UP)
                break
                ;;
            ERROR)
                echo "Provisioning failed; fetching the cloud-init log:"
                cluster_ssh "sudo tail -100 /var/log/cloud-init-output.log" || true
                fail "Error: provisioning failed"
                ;;
            *)
                sleep 15
                ;;
        esac
    done
    if [ "$provision_status" != "UP" ]; then
        fail "Error: timed out waiting for provisioning to complete (last status: $provision_status)"
    fi
    echo "Provisioning complete"

    # The kubeconfig k3s writes names the local address; the machine's FQDN is in
    # the API server certificate (k3s-node.sh adds $MACHINE_FQDN as a tls-san), so
    # substituting it yields a kubeconfig that works remotely.
    cluster_ssh "sudo cat /etc/rancher/k3s/k3s.yaml" | sed "s/127.0.0.1/${machine_fqdn}/g" > "$kube_config"
    chmod 600 "$kube_config"
    if ! grep -q "$machine_fqdn" "$kube_config"; then
        fail "Error: failed to fetch a usable kubeconfig from the machine"
    fi
    echo "Fetched kubeconfig"

    # What the cluster provisioned itself with, recorded on every run rather than only on a
    # failing one. The provisioning installs these charts unpinned, so "which version did that
    # run actually test?" is otherwise unanswerable after the VM is destroyed -- which is
    # exactly the question a backup result raises when it disagrees with the engine's own
    # documentation.
    cluster_ssh \
        "sudo kubectl get deploy -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name} {..image}{\"\n\"}{end}'" \
        2>/dev/null | grep -E "k8up|cert-manager|traefik" || true

    # So that push-images can push to the registry.  The token is an argument here,
    # so under STACK_SCRIPT_DEBUG it would be echoed verbatim by xtrace; suppress
    # tracing across the login and restore whatever it was afterward.  (Heredoc
    # bodies and pipe contents are not traced, so the machine config and the
    # kubeconfig need no such guard.)
    local xtrace_was_set=""
    case $- in *x*) xtrace_was_set=1; set +x ;; esac
    echo "$STACK_IMAGE_REGISTRY_TOKEN" | docker login "${STACK_IMAGE_REGISTRY%%/*}" \
        --username "$STACK_IMAGE_REGISTRY_USER" --password-stdin
    if [ -n "$xtrace_was_set" ]; then set -x; fi

    # The test hostname must resolve locally before the HTTP checks can pass (the
    # authoritative record was just created; Let's Encrypt resolves it
    # independently).
    echo "Waiting for $machine_fqdn to resolve..."
    for _ in {1..60}; do
        if getent hosts "$machine_fqdn" > /dev/null; then
            break
        fi
        sleep 5
    done

    # What a test needs to reach this cluster, and nothing else: the tests read
    # these through select_deploy_target.
    publish_setting STACK_TEST_TARGET remote
    publish_setting STACK_KUBE_CONFIG "$kube_config"
    publish_setting STACK_K8S_HOSTNAME "$machine_fqdn"
    publish_setting STACK_IMAGE_REGISTRY "$STACK_IMAGE_REGISTRY"
    # And, for the one test whose subject is data at a path on the node itself
    # (tests/volumes), how to run a command there.  Published as a whole command
    # rather than its pieces so that the user name and host-key handling stay
    # here, alongside cluster_ssh which they are copied from.
    publish_setting STACK_TEST_NODE_SSH_COMMAND \
        "ssh -i $MACHINE_SSH_KEY_FILE -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$known_hosts ${MACHINE_NEW_USER}@${machine_fqdn}"
    echo "Cluster ready at $machine_fqdn"
}

# The machine is destroyed when the run ends, so cluster state has to be captured
# while the failure is fresh -- afterwards there is nothing left to look at.
diagnostics () {
    if [ ! -f "$fqdn_file" ]; then
        echo "No cluster to collect diagnostics from"
        return
    fi
    echo "----- cluster diagnostics -----"
    cluster_ssh \
        "sudo kubectl get pods -A -o wide; \
         sudo kubectl get gateway,httproute -A 2>/dev/null; \
         sudo kubectl get ingress -A 2>/dev/null; \
         sudo kubectl get certificate,order,challenge -A 2>/dev/null; \
         sudo kubectl describe gateway -A 2>/dev/null" || true
}

# Destroying is safe to call when there is nothing to destroy: it is wired to run
# however a run ends, including ones that failed before creating anything.
destroy () {
    if [ ! -f "$machine_id_file" ]; then
        echo "No machine to destroy"
        rm -rf "$STACK_K3S_STATE_DIR"
        return
    fi
    local machine_id
    machine_id=$( cat "$machine_id_file" )
    echo "Destroying machine $( cat "$fqdn_file" ) ($machine_id)"
    $MACHINE_CMD --config-file "$machine_config" destroy --no-confirm --delete-dns "$machine_id"
    # Only once the provider has confirmed it: the state directory is the record
    # of a machine that still exists, and holds the token needed to remove it.
    rm -rf "$STACK_K3S_STATE_DIR"
}

case "${1:-}" in
    provision)   provision ;;
    diagnostics) diagnostics ;;
    destroy)     destroy ;;
    *)
        echo "Usage: $0 provision|diagnostics|destroy"
        echo "Runs tests against the cluster in between: see with-k3s-cluster.sh"
        exit 1
        ;;
esac
