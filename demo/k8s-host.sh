#!/usr/bin/env bash
#
# Create, inspect and destroy the Kubernetes host used by the quick-start
# recording.
#
# The recording (demo/quickstart.tape) deploys the same stack twice: once to
# local Docker, then to a real single-node k3s cluster with a real hostname and
# a real Let's Encrypt certificate. That cluster lives on a cloud VM, which
# takes several minutes and real money to provision -- far too slow to do on
# every take. So the VM's lifecycle is separate from the recording's:
#
#     ./demo/k8s-host.sh create      # once, ~5 minutes
#     ./demo/record-quickstart.sh    # as many takes as you like
#     ./demo/k8s-host.sh destroy     # when you are done for the day
#
# The VM is provisioned exactly the way the k3s CI job provisions its test
# cluster (tests/k3s-deploy/with-k3s-cluster.sh) -- the same "machine"
# utility, the same machine-provisioning scripts, the same environment variable
# names -- so a host that works for one works for the other.
#
# State (the machine's name, id and FQDN, and a kubeconfig that reaches it) is
# written to $STACK_DEMO_STATE_DIR, where record-quickstart.sh picks it up.
#
# Requires: machine (https://github.com/stirlingbridge/machine), jq, ssh.
#
# Required environment (same names the k3s test takes):
#   MACHINE_DO_TOKEN         DigitalOcean API token
#   MACHINE_SSH_KEY_NAME     Name of an SSH key registered at the provider
#   MACHINE_SSH_KEY_FILE     Path to the matching private key file
#   MACHINE_DNS_ZONE         DNS zone hosted at the provider; the demo hostname
#                            is a name under this zone
#   STACK_IMAGE_REGISTRY     Registry the demo's images are pushed to and the
#                            cluster pulls them from, including any org path
#   STACK_IMAGE_REGISTRY_USER
#   STACK_IMAGE_REGISTRY_TOKEN
#                            Credentials for that registry (for a DigitalOcean
#                            registry, pass the API token as both)
#   LETSENCRYPT_EMAIL        Let's Encrypt contact address
#
# Optional environment:
#   STACK_DEMO_STATE_DIR     Where to keep the host state
#                            (default ~/.cache/stack-demo/k8s-host)
#   STACK_DEMO_MACHINE_NAME  Machine hostname under the zone (default stackdemo)
#   MACHINE_REGION           Provider region (default nyc3)
#   MACHINE_SIZE             Machine size slug (default s-2vcpu-4gb)
#   MACHINE_IMAGE            Machine image (default ubuntu-24-04-x64)
#   MACHINE_PROJECT          DigitalOcean project to assign the VM to
#   MACHINE_PROVISIONING_URL URL of combine.sh (default: the main branch)
#   MACHINE_CMD              The machine command to run (default: machine)
#
set -e

if [ -n "$STACK_SCRIPT_DEBUG" ]; then
  set -x
fi

MACHINE_CMD=${MACHINE_CMD:-machine}
MACHINE_REGION=${MACHINE_REGION:-nyc3}
MACHINE_SIZE=${MACHINE_SIZE:-s-2vcpu-4gb}
MACHINE_IMAGE=${MACHINE_IMAGE:-ubuntu-24-04-x64}
MACHINE_PROVISIONING_URL=${MACHINE_PROVISIONING_URL:-https://raw.githubusercontent.com/stirlingbridge/machine-provisioning/refs/heads/main/scripts/combine.sh}
MACHINE_NEW_USER=stackdemo

STATE_DIR=${STACK_DEMO_STATE_DIR:-$HOME/.cache/stack-demo/k8s-host}
MACHINE_NAME=${STACK_DEMO_MACHINE_NAME:-stackdemo}

# The demo deploys to the Gateway API arrangement (k3s-node.sh's own default),
# which is what gets the application its own Let's Encrypt certificate.
machine_config=$STATE_DIR/machine-config.yml
host_env=$STATE_DIR/host.env
kube_config=$STATE_DIR/kubeconfig

# How long to allow for the VM to boot and cloud-init to install k3s,
# cert-manager etc. (seconds).
PROVISION_TIMEOUT=1800

usage () {
  cat <<'USAGE'
Usage: demo/k8s-host.sh <command>

  create    Provision the demo's k3s host (no-op if one already exists)
  info      Print the current host's name, id and FQDN
  destroy   Destroy the host and delete its DNS record
USAGE
}

require_tools () {
  for cmd in "$MACHINE_CMD" jq ssh; do
    if ! command -v "$cmd" &> /dev/null; then
      echo "Error: $cmd is not installed." >&2
      exit 1
    fi
  done
}

require_env () {
  missing=""
  for var in MACHINE_DO_TOKEN MACHINE_SSH_KEY_NAME MACHINE_SSH_KEY_FILE MACHINE_DNS_ZONE \
             STACK_IMAGE_REGISTRY STACK_IMAGE_REGISTRY_USER STACK_IMAGE_REGISTRY_TOKEN LETSENCRYPT_EMAIL; do
    if [ -z "${!var}" ]; then
      missing="$missing $var"
    fi
  done
  if [ -n "$missing" ]; then
    echo "Error: required environment not set:$missing" >&2
    exit 1
  fi
  if [ ! -f "$MACHINE_SSH_KEY_FILE" ]; then
    echo "Error: MACHINE_SSH_KEY_FILE $MACHINE_SSH_KEY_FILE does not exist" >&2
    exit 1
  fi
}

write_machine_config () {
  # The registry credentials in script-args end up in the VM's cloud-init user
  # data; use a registry and credentials dedicated to demos and testing.
  # health.sh serves the status endpoint that "machine status" polls;
  # k3s-node.sh needs the registry credentials so the cluster can pull the
  # demo's images.
  mkdir -p "$STATE_DIR"
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
        script-dir: /opt/stackdemo
        script-url: ${MACHINE_PROVISIONING_URL}
        script-path: /opt/stackdemo/combine.sh
        script-args:
          - health.sh
          - fqdn.sh
          - k3s-node.sh -y --letsencrypt-email ${LETSENCRYPT_EMAIL} --image-registry ${STACK_IMAGE_REGISTRY} --image-registry-username ${STACK_IMAGE_REGISTRY_USER} --image-registry-password ${STACK_IMAGE_REGISTRY_TOKEN}
EOF
  chmod 600 "$machine_config"
}

machine_ssh () {
  ssh -i "$MACHINE_SSH_KEY_FILE" -o StrictHostKeyChecking=accept-new \
    -o UserKnownHostsFile="$STATE_DIR/known_hosts" "${MACHINE_NEW_USER}@${1}" "$2"
}

do_create () {
  require_tools
  require_env

  machine_fqdn="${MACHINE_NAME}.${MACHINE_DNS_ZONE}"

  if [ -f "$host_env" ]; then
    # shellcheck disable=SC1090
    . "$host_env"
    if [ -f "$machine_config" ] && \
       [ "$($MACHINE_CMD --config-file "$machine_config" list --id "$STACK_DEMO_MACHINE_ID" --output json 2>/dev/null \
            | jq -r 'length' 2>/dev/null)" == "1" ]; then
      echo "Demo k8s host already exists:"
      do_info
      echo
      echo "Destroy it with ./demo/k8s-host.sh destroy, or record with ./demo/record-quickstart.sh"
      return 0
    fi
    echo "Stale host state in $STATE_DIR (no such machine); re-creating"
    rm -f "$host_env" "$kube_config"
  fi

  write_machine_config

  echo "Creating machine $machine_fqdn"
  $MACHINE_CMD --config-file "$machine_config" create --name "$MACHINE_NAME" --type k8s-stack-host --wait-for-ip

  machine_id=$($MACHINE_CMD --config-file "$machine_config" list --name "$MACHINE_NAME" --output json | jq -r '.[0].id')
  if [ -z "$machine_id" ] || [ "$machine_id" == "null" ]; then
    echo "Error: could not determine the id of the created machine" >&2
    exit 1
  fi
  echo "Machine created with id $machine_id"
  # Record the id before provisioning finishes, so a failed or interrupted
  # provision still leaves something "destroy" can clean up.
  cat > "$host_env" <<EOF
STACK_DEMO_MACHINE_NAME=${MACHINE_NAME}
STACK_DEMO_MACHINE_ID=${machine_id}
STACK_DEMO_MACHINE_FQDN=${machine_fqdn}
EOF

  echo "Waiting for provisioning to complete (up to ${PROVISION_TIMEOUT}s)..."
  start_time=$SECONDS
  provision_status="UNKNOWN"
  while [ $((SECONDS - start_time)) -lt $PROVISION_TIMEOUT ]; do
    provision_status=$($MACHINE_CMD --config-file "$machine_config" status --id "$machine_id" --output json \
      | jq -r '.[0]["cloud-init-status"]')
    case "$provision_status" in
      UP)
        break
        ;;
      ERROR)
        echo "Provisioning failed; fetching the cloud-init log:" >&2
        machine_ssh "$machine_fqdn" "sudo tail -100 /var/log/cloud-init-output.log" || true
        exit 1
        ;;
      *)
        sleep 15
        ;;
    esac
  done
  if [ "$provision_status" != "UP" ]; then
    echo "Error: timed out waiting for provisioning to complete (last status: $provision_status)" >&2
    exit 1
  fi
  echo "Provisioning complete"

  # The kubeconfig k3s writes names the local address; the machine's FQDN is in
  # the API server certificate (k3s-node.sh adds it as a tls-san), so
  # substituting it yields a kubeconfig that works remotely.
  machine_ssh "$machine_fqdn" "sudo cat /etc/rancher/k3s/k3s.yaml" \
    | sed "s/127.0.0.1/${machine_fqdn}/g" > "$kube_config"
  chmod 600 "$kube_config"
  if ! grep -q "$machine_fqdn" "$kube_config"; then
    echo "Error: failed to fetch a usable kubeconfig from the machine" >&2
    exit 1
  fi
  echo "Fetched kubeconfig to $kube_config"

  # The hostname must resolve locally before the recording's HTTPS checks can
  # pass (the authoritative record was just created; Let's Encrypt resolves it
  # independently).
  echo "Waiting for $machine_fqdn to resolve..."
  for _ in {1..60}; do
    if getent hosts "$machine_fqdn" > /dev/null; then
      break
    fi
    sleep 5
  done

  echo
  echo "Demo k8s host ready:"
  do_info
  echo
  echo "Now record with ./demo/record-quickstart.sh, and destroy the host with"
  echo "./demo/k8s-host.sh destroy when you are finished."
}

do_info () {
  if [ ! -f "$host_env" ]; then
    echo "No demo k8s host (nothing in $STATE_DIR)."
    echo "Create one with ./demo/k8s-host.sh create"
    return 1
  fi
  # shellcheck disable=SC1090
  . "$host_env"
  echo "  name:       $STACK_DEMO_MACHINE_NAME"
  echo "  id:         $STACK_DEMO_MACHINE_ID"
  echo "  fqdn:       $STACK_DEMO_MACHINE_FQDN"
  echo "  kubeconfig: $kube_config"
}

do_destroy () {
  require_tools
  if [ ! -f "$host_env" ]; then
    echo "No demo k8s host to destroy (nothing in $STATE_DIR)."
    return 0
  fi
  # shellcheck disable=SC1090
  . "$host_env"
  echo "Destroying machine $STACK_DEMO_MACHINE_NAME ($STACK_DEMO_MACHINE_ID)"
  $MACHINE_CMD --config-file "$machine_config" destroy --no-confirm --delete-dns "$STACK_DEMO_MACHINE_ID"
  rm -rf "$STATE_DIR"
  echo "Destroyed"
}

case "${1:-}" in
  create)
    do_create
    ;;
  info)
    do_info
    ;;
  destroy)
    do_destroy
    ;;
  ""|-h|--help|help)
    usage
    ;;
  *)
    echo "Error: unknown command '$1'" >&2
    usage >&2
    exit 1
    ;;
esac
