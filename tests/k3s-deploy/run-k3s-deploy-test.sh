#!/usr/bin/env bash
#
# Deploy test against a real k3s cluster on a real cloud VM.
#
# Provisions a single-node k3s cluster by invoking the "machine" utility with a
# config that runs the machine-provisioning combine.sh/k3s-node.sh scripts on
# first boot, then runs the standard k8s deploy test (tests/k8s-deploy) against
# it in remote mode. Unlike the kind-based run of that test, this exercises the
# whole production arrangement: a remote kubeconfig, images pushed to and
# pulled from a real registry, DNS, and HTTPS with a real Let's Encrypt
# certificate obtained over ACME HTTP-01.
#
# The VM is destroyed (and its DNS record deleted) on exit, pass or fail.
#
# Requires: machine (https://github.com/stirlingbridge/machine), docker, jq,
# ssh. The SSH key named by MACHINE_SSH_KEY_NAME must be registered with the
# cloud provider, and MACHINE_SSH_KEY_FILE must be the matching private key --
# it is used to fetch the cluster's kubeconfig from the VM.
#
# Required environment:
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
set -e

if [ -n "$STACK_SCRIPT_DEBUG" ]; then
  set -x
fi

script_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

MACHINE_CMD=${MACHINE_CMD:-machine}
MACHINE_REGION=${MACHINE_REGION:-nyc3}
MACHINE_SIZE=${MACHINE_SIZE:-s-2vcpu-4gb}
MACHINE_IMAGE=${MACHINE_IMAGE:-ubuntu-24-04-x64}
MACHINE_PROVISIONING_URL=${MACHINE_PROVISIONING_URL:-https://raw.githubusercontent.com/stirlingbridge/machine-provisioning/refs/heads/main/scripts/combine.sh}
STACK_K3S_MODE=${STACK_K3S_MODE:-gateway}
MACHINE_NEW_USER=stacktest

# How long to allow for the VM to boot and cloud-init to install k3s,
# cert-manager etc. (seconds).
PROVISION_TIMEOUT=1800

for cmd in "$MACHINE_CMD" jq ssh docker; do
  if ! command -v "$cmd" &> /dev/null; then
    echo "Error: $cmd is not installed."
    exit 1
  fi
done

missing=""
for var in MACHINE_DO_TOKEN MACHINE_SSH_KEY_NAME MACHINE_SSH_KEY_FILE MACHINE_DNS_ZONE \
           STACK_IMAGE_REGISTRY STACK_IMAGE_REGISTRY_USER STACK_IMAGE_REGISTRY_TOKEN LETSENCRYPT_EMAIL; do
  if [ -z "${!var}" ]; then
    missing="$missing $var"
  fi
done
if [ -n "$missing" ]; then
  echo "Error: required environment not set:$missing"
  exit 1
fi

if [ ! -f "$MACHINE_SSH_KEY_FILE" ]; then
  echo "Error: MACHINE_SSH_KEY_FILE $MACHINE_SSH_KEY_FILE does not exist"
  exit 1
fi

case "$STACK_K3S_MODE" in
  gateway)
    k3s_mode_args=""
    ;;
  ingress)
    k3s_mode_args="--nginx-ingress"
    ;;
  *)
    echo "Error: STACK_K3S_MODE must be gateway or ingress, not $STACK_K3S_MODE"
    exit 1
    ;;
esac

work_dir=$(mktemp -d)
machine_config=$work_dir/config.yml
machine_id=""

# A machine-unique name gives a unique FQDN, which keeps runs independent and
# avoids Let's Encrypt duplicate-certificate rate limits.
machine_name="stackk3s-$(head -c4 /dev/urandom | od -An -tx1 | tr -d ' \n')"
machine_fqdn="${machine_name}.${MACHINE_DNS_ZONE}"

cleanup () {
  rc=$?
  set +e
  if [ -n "$machine_id" ]; then
    echo "Destroying machine $machine_name ($machine_id)"
    $MACHINE_CMD --config-file "$machine_config" destroy --no-confirm --delete-dns "$machine_id"
  fi
  rm -rf "$work_dir"
  exit $rc
}
trap cleanup EXIT

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

machine_id=$($MACHINE_CMD --config-file "$machine_config" list --name "$machine_name" --output json | jq -r '.[0].id')
if [ -z "$machine_id" ] || [ "$machine_id" == "null" ]; then
  echo "Error: could not determine the id of the created machine"
  machine_id=""
  exit 1
fi
echo "Machine created with id $machine_id"

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
      echo "Provisioning failed; fetching the cloud-init log:"
      ssh -i "$MACHINE_SSH_KEY_FILE" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$work_dir/known_hosts" \
        ${MACHINE_NEW_USER}@${machine_fqdn} "sudo tail -100 /var/log/cloud-init-output.log" || true
      exit 1
      ;;
    *)
      sleep 15
      ;;
  esac
done
if [ "$provision_status" != "UP" ]; then
  echo "Error: timed out waiting for provisioning to complete (last status: $provision_status)"
  exit 1
fi
echo "Provisioning complete"

# The kubeconfig k3s writes names the local address; the machine's FQDN is in
# the API server certificate (k3s-node.sh adds $MACHINE_FQDN as a tls-san), so
# substituting it yields a kubeconfig that works remotely.
kube_config=$work_dir/kubeconfig
ssh -i "$MACHINE_SSH_KEY_FILE" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$work_dir/known_hosts" \
  ${MACHINE_NEW_USER}@${machine_fqdn} "sudo cat /etc/rancher/k3s/k3s.yaml" \
  | sed "s/127.0.0.1/${machine_fqdn}/g" > "$kube_config"
chmod 600 "$kube_config"
if ! grep -q "$machine_fqdn" "$kube_config"; then
  echo "Error: failed to fetch a usable kubeconfig from the machine"
  exit 1
fi
echo "Fetched kubeconfig"

# So that push-images can push to the registry.
echo "$STACK_IMAGE_REGISTRY_TOKEN" | docker login "${STACK_IMAGE_REGISTRY%%/*}" \
  --username "$STACK_IMAGE_REGISTRY_USER" --password-stdin

# The test hostname must resolve locally before the HTTP checks can pass (the
# authoritative record was just created; Let's Encrypt resolves it
# independently).
echo "Waiting for $machine_fqdn to resolve..."
for i in {1..60}; do
  if getent hosts "$machine_fqdn" > /dev/null; then
    break
  fi
  sleep 5
done

# Hand over to the standard k8s deploy test in remote mode.
export STACK_K8S_REMOTE=true
export STACK_KUBE_CONFIG=$kube_config
export STACK_K8S_HOSTNAME=$machine_fqdn
export STACK_IMAGE_REGISTRY

echo "Running the k8s deploy test against $machine_fqdn"
if ! "${script_dir}/../k8s-deploy/run-deploy-test.sh"; then
  # The machine is destroyed on exit, so capture cluster state now.
  echo "Test failed; dumping cluster diagnostics:"
  ssh -i "$MACHINE_SSH_KEY_FILE" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$work_dir/known_hosts" \
    ${MACHINE_NEW_USER}@${machine_fqdn} \
    "sudo kubectl get pods -A -o wide; \
     sudo kubectl get gateway,httproute -A 2>/dev/null; \
     sudo kubectl get ingress -A 2>/dev/null; \
     sudo kubectl get certificate,order,challenge -A 2>/dev/null; \
     sudo kubectl describe gateway -A 2>/dev/null" || true
  exit 1
fi
