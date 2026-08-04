#!/usr/bin/env bash
#
# Record docs/images/quickstart.gif from demo/quickstart.tape.
#
# The recording is a real run of the README quick start — no output is faked.
# It deploys the example todo stack twice: to local Docker, then the same stack
# to a real Kubernetes cluster, over HTTPS with a real Let's Encrypt
# certificate.
#
# The cluster is NOT created here. Provisioning a cloud VM takes minutes and
# costs money, and this script is expected to be run many times over while
# getting a take you like, so the host has its own lifecycle:
#
#     ./demo/k8s-host.sh create      # once
#     ./demo/record-quickstart.sh    # as many takes as you like
#     ./demo/k8s-host.sh destroy     # when you are done
#
# To keep the animation short enough to work as a README animation, this script
# prepares state off camera so that each recorded command does genuine work but
# returns quickly:
#
#   * STACK_REPO_BASE_DIR points at a scratch dir, so the recorded `stack fetch`
#     performs a real clone. This also means your existing clones under
#     ~/.config/stack/repos are never touched.
#   * The todo image *tags* are removed, but Docker's build layer cache is left
#     intact, so the recorded `stack prepare` runs a real build (~8s) rather
#     than reporting "existing-image" or rebuilding from scratch (minutes).
#   * The images are pushed to the registry off camera, so the recorded
#     `stack manage push-images` pushes a real (already-present) image set in
#     seconds rather than uploading hundreds of megabytes on camera.
#
# quickstart.tape is a template: the Kubernetes host's FQDN, kubeconfig path
# and image registry are only known once the host exists, so they appear in the
# tape as @@...@@ placeholders and are substituted here into a rendered copy
# under the scratch dir, which is what vhs actually runs.
#
# Requires: vhs, ttyd, ffmpeg, docker, jq, openssl, kubectl, and the `stack` CLI
# on PATH, plus STACK_IMAGE_REGISTRY / STACK_IMAGE_REGISTRY_USER /
# STACK_IMAGE_REGISTRY_TOKEN for the registry the cluster pulls from.

set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$PWD"
# Deliberately outside $HOME: `stack fetch` prints the absolute clone destination,
# so a scratch dir under $HOME would put the recorder's username in the recording.
SCRATCH="/tmp/stack-demo"
DEPLOYMENT="$HOME/deployments/todo-demo"
K8S_DEPLOYMENT="$HOME/deployments/todo-k8s"

STATE_DIR=${STACK_DEMO_STATE_DIR:-$HOME/.cache/stack-demo/k8s-host}
# The kubeconfig is copied into the scratch dir because the recorded `stack
# init` and `export KUBECONFIG` lines both show its path, and a path under
# $HOME would put the recorder's username in the recording.
DEMO_KUBE_CONFIG="$SCRATCH/kubeconfig"

export STACK_REPO_BASE_DIR="$SCRATCH/repos"

missing=()
for tool in vhs ttyd ffmpeg docker jq openssl kubectl stack; do
    command -v "$tool" >/dev/null || missing+=("$tool")
done
if [ ${#missing[@]} -gt 0 ]; then
    echo "error: not on PATH: ${missing[*]}" >&2
    echo "  ffmpeg, ttyd: sudo apt-get install -y ffmpeg ttyd" >&2
    echo "  vhs:          https://github.com/charmbracelet/vhs/releases" >&2
    exit 1
fi

if [ ! -f "$STATE_DIR/host.env" ] || [ ! -f "$STATE_DIR/kubeconfig" ]; then
    echo "error: no Kubernetes host to record against (looked in $STATE_DIR)" >&2
    echo "  create one with: ./demo/k8s-host.sh create" >&2
    exit 1
fi
# shellcheck disable=SC1091
. "$STATE_DIR/host.env"

missing=()
for var in STACK_IMAGE_REGISTRY STACK_IMAGE_REGISTRY_USER STACK_IMAGE_REGISTRY_TOKEN; do
    [ -n "${!var:-}" ] || missing+=("$var")
done
if [ ${#missing[@]} -gt 0 ]; then
    echo "error: required environment not set: ${missing[*]}" >&2
    exit 1
fi

# The host port a service maps to comes from the stack, and the stack is free to
# change it (it has). Read the ports out of a spec generated the same way the
# recording generates its own, rather than hardcoding them here and in the tape.
# Emits "service host-port" per line.
spec_host_ports () {
    awk '
        /^  ports:/            { in_ports = 1; next }
        !in_ports              { next }
        /^    [A-Za-z0-9_-]+:/ { svc = $1; sub(":", "", svc); next }
        /^ *- /                { n = split($2, a, ":"); print svc, (n == 3 ? a[2] : a[1]); next }
        /^  [A-Za-z]/          { in_ports = 0 }
    ' "$1"
}

k8s_stop () {
    # Best effort — the deployment may already be stopped, or never started.
    # --delete-volumes drops the database so the recorded todo list starts
    # empty, the same as the Docker half.
    if [ -d "$K8S_DEPLOYMENT" ]; then
        stack manage --dir "$K8S_DEPLOYMENT" stop --delete-volumes || true
        rm -rf "$K8S_DEPLOYMENT"
    fi
}

echo "==> Recording against Kubernetes host $STACK_DEMO_MACHINE_FQDN"

echo "==> Cleaning previous demo state"
if [ -d "$DEPLOYMENT" ]; then
    stack manage --dir "$DEPLOYMENT" stop || true
    rm -rf "$DEPLOYMENT"
fi
k8s_stop
rm -rf "$SCRATCH"
mkdir -p "$SCRATCH/repos"
cp "$STATE_DIR/kubeconfig" "$DEMO_KUBE_CONFIG"
chmod 600 "$DEMO_KUBE_CONFIG"
# Note: ~/deployments is deliberately NOT created here. `stack deploy` requires
# the parent of --deployment-dir to already exist, and the tape creates it on
# camera so the recording matches the README.
rmdir "$HOME/deployments" 2>/dev/null || true

echo "==> Warming the build cache (off camera)"
cd "$SCRATCH"
stack fetch repo bozemanpass/example-todo-list
stack prepare --stack todo

echo "==> Pushing the images to $STACK_IMAGE_REGISTRY (off camera)"
echo "$STACK_IMAGE_REGISTRY_TOKEN" | docker login "${STACK_IMAGE_REGISTRY%%/*}" \
    --username "$STACK_IMAGE_REGISTRY_USER" --password-stdin
# push-images works from a deployment, so make a throwaway one. It is never
# started, so nothing reaches the cluster here — only the registry.
warm_spec="$SCRATCH/warm-k8s.yml"
warm_dir="$SCRATCH/warm-k8s-deployment"
stack init --stack todo --output "$warm_spec" --deploy-to k8s \
    --kube-config "$DEMO_KUBE_CONFIG" --image-registry "$STACK_IMAGE_REGISTRY" \
    --http-proxy-fqdn "$STACK_DEMO_MACHINE_FQDN"
stack deploy --spec-file "$warm_spec" --deployment-dir "$warm_dir"
stack manage --dir "$warm_dir" push-images
rm -rf "$warm_dir" "$warm_spec"

echo "==> Working out the host ports this stack maps to"
probe_spec="$SCRATCH/host-ports.yml"
stack init --stack todo --output "$probe_spec" --deploy-to compose --map-ports-to-host localhost-same
frontend_port=$(spec_host_ports "$probe_spec" | awk '$1 == "frontend" { print $2; exit }')
api_port=$(spec_host_ports "$probe_spec" | awk '$1 == "backend" { print $2; exit }')
if [ -z "$frontend_port" ] || [ -z "$api_port" ]; then
    echo "error: could not read the frontend/backend host ports from $probe_spec" >&2
    exit 1
fi
# Bare "localhost" reads better than "localhost:80" in the recording.
if [ "$frontend_port" = "80" ]; then
    frontend_url="localhost"
else
    frontend_url="localhost:$frontend_port"
fi
api_url="localhost:$api_port"
echo "    frontend: $frontend_url   api: $api_url"

# The Docker half maps the stack's ports to the same ports on localhost, and the
# recording proves the deployment works by curling them. Anything else already
# listening on one of them would answer those curls instead, and the recording
# would look like a pass while showing someone else's container.
echo "==> Checking those ports are free"
busy=()
while read -r _ port; do
    if (ss -ltn "sport = :$port" 2>/dev/null || netstat -ltn 2>/dev/null) | grep -qE "[:.]$port\b"; then
        busy+=("$port")
    fi
done < <(spec_host_ports "$probe_spec")
if [ ${#busy[@]} -gt 0 ]; then
    echo "error: something is already listening on: ${busy[*]}" >&2
    echo "  The recorded curls would hit it instead of the demo deployment." >&2
    echo "  Stop it and try again — e.g. a stray copy of the example app:" >&2
    echo "    docker ps --filter name=example-todo-list" >&2
    exit 1
fi
rm -f "$probe_spec"

echo "==> Dropping image tags so the recorded build is real but cached"
docker images --format '{{.Repository}}:{{.Tag}}' \
    | grep -E '^bozemanpass/todo-' \
    | xargs -r docker rmi >/dev/null 2>&1 || true

echo "==> Resetting the scratch clone so the recorded fetch is a real clone"
rm -rf "$SCRATCH/repos"
mkdir -p "$SCRATCH/repos"

echo "==> Rendering the tape for this host"
cd "$REPO_ROOT"
rendered_tape="$SCRATCH/quickstart.tape"
sed -e "s|@@K8S_FQDN@@|$STACK_DEMO_MACHINE_FQDN|g" \
    -e "s|@@KUBE_CONFIG@@|$DEMO_KUBE_CONFIG|g" \
    -e "s|@@IMAGE_REGISTRY@@|$STACK_IMAGE_REGISTRY|g" \
    -e "s|@@FRONTEND_URL@@|$frontend_url|g" \
    -e "s|@@API_URL@@|$api_url|g" \
    demo/quickstart.tape > "$rendered_tape"

echo "==> Recording"
# vhs resolves the tape's Output path against its own cwd, so stay at the repo
# root even though the tape itself lives under the scratch dir.
vhs "$rendered_tape"

echo "==> Cleaning up"
if [ -d "$DEPLOYMENT" ]; then
    stack manage --dir "$DEPLOYMENT" stop || true
    rm -rf "$DEPLOYMENT"
fi
k8s_stop
rm -rf "$SCRATCH"

echo
echo "Wrote $REPO_ROOT/docs/images/quickstart.gif"
ls -lh "$REPO_ROOT/docs/images/quickstart.gif"
echo
echo "The Kubernetes host is still running. Destroy it with:"
echo "  ./demo/k8s-host.sh destroy"
