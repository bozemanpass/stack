#!/usr/bin/env bash
#
# Record docs/images/quickstart.gif from demo/quickstart.tape.
#
# The recording is a real run of the README quick start — no output is faked.
# To keep it short enough to work as a README animation, this script prepares
# state off camera so that each recorded command does genuine work but returns
# quickly:
#
#   * STACK_REPO_BASE_DIR points at a scratch dir, so the recorded `stack fetch`
#     performs a real clone. This also means your existing clones under
#     ~/.config/stack/repos are never touched.
#   * The todo image *tags* are removed, but Docker's build layer cache is left
#     intact, so the recorded `stack prepare` runs a real build (~8s) rather
#     than reporting "existing-image" or rebuilding from scratch (minutes).
#
# Requires: vhs, ttyd, ffmpeg, docker, and the `stack` CLI on PATH.

set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$PWD"
# Deliberately outside $HOME: `stack fetch` prints the absolute clone destination,
# so a scratch dir under $HOME would put the recorder's username in the recording.
SCRATCH="/tmp/stack-demo"
DEPLOYMENT="$HOME/deployments/todo-demo"

export STACK_REPO_BASE_DIR="$SCRATCH/repos"

missing=()
for tool in vhs ttyd ffmpeg docker stack; do
    command -v "$tool" >/dev/null || missing+=("$tool")
done
if [ ${#missing[@]} -gt 0 ]; then
    echo "error: not on PATH: ${missing[*]}" >&2
    echo "  ffmpeg, ttyd: sudo apt-get install -y ffmpeg ttyd" >&2
    echo "  vhs:          https://github.com/charmbracelet/vhs/releases" >&2
    exit 1
fi

echo "==> Cleaning previous demo state"
if [ -d "$DEPLOYMENT" ]; then
    # Best effort — the deployment may already be stopped.
    stack manage --dir "$DEPLOYMENT" stop || true
    rm -rf "$DEPLOYMENT"
fi
rm -rf "$SCRATCH"
mkdir -p "$SCRATCH/repos"
# Note: ~/deployments is deliberately NOT created here. `stack deploy` requires
# the parent of --deployment-dir to already exist, and the tape creates it on
# camera so the recording matches the README.
rmdir "$HOME/deployments" 2>/dev/null || true

echo "==> Warming the build cache (off camera)"
cd "$SCRATCH"
stack fetch repo bozemanpass/example-todo-list
stack prepare --stack todo

echo "==> Dropping image tags so the recorded build is real but cached"
docker images --format '{{.Repository}}:{{.Tag}}' \
    | grep -E '^bozemanpass/todo-' \
    | xargs -r docker rmi >/dev/null 2>&1 || true

echo "==> Resetting the scratch clone so the recorded fetch is a real clone"
rm -rf "$SCRATCH/repos"
mkdir -p "$SCRATCH/repos"

echo "==> Recording"
cd "$REPO_ROOT"
vhs demo/quickstart.tape

echo "==> Cleaning up"
if [ -d "$DEPLOYMENT" ]; then
    stack manage --dir "$DEPLOYMENT" stop || true
    rm -rf "$DEPLOYMENT"
fi
rm -rf "$SCRATCH"

echo
echo "Wrote $REPO_ROOT/docs/images/quickstart.gif"
ls -lh "$REPO_ROOT/docs/images/quickstart.gif"
