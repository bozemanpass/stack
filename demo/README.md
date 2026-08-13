# Demo recordings

`docs/images/quickstart.gif`, the animation at the top of the project README, is
recorded from `quickstart.tape` by [vhs](https://github.com/charmbracelet/vhs).
Nothing in it is faked or edited: every command really runs, against the
[example todo stack](https://github.com/bozemanpass/example-todo-list), and it
deploys that stack twice — first to local Docker, then the same stack, unchanged
except for its deployment spec, to a real single-node Kubernetes (k3s) cluster
on a cloud VM, reached over HTTPS with a real Let's Encrypt certificate.

## Recording it

The Kubernetes cluster is provisioned separately from the recording, because
creating a VM and installing k3s, cert-manager and the rest takes minutes and
costs money, while getting a take you like usually means recording several
times:

```bash
./demo/k8s-host.sh create      # once, ~5 minutes
./demo/record-quickstart.sh    # as many takes as you like
./demo/k8s-host.sh destroy     # when you are done for the day
```

`k8s-host.sh info` prints the current host. The host state (its name, id and
FQDN, and a kubeconfig that reaches it) lives in `~/.cache/stack-demo/k8s-host`,
overridable with `STACK_DEMO_STATE_DIR`.

## Requirements

* `vhs`, `ttyd`, `ffmpeg`, `docker`, `jq`, `openssl`, `kubectl`, and `stack` on `PATH`
  (`sudo apt-get install -y ffmpeg ttyd`; vhs from its
  [releases page](https://github.com/charmbracelet/vhs/releases))
* [`machine`](https://github.com/stirlingbridge/machine), for `k8s-host.sh`
* Environment for the cloud host and the image registry — the same variable
  names the k3s CI job passes to `tests/k3s-deploy/with-k3s-cluster.sh`:
  `MACHINE_DO_TOKEN`, `MACHINE_SSH_KEY_NAME`, `MACHINE_SSH_KEY_FILE`,
  `MACHINE_DNS_ZONE`, `MACHINE_PROJECT`, `STACK_IMAGE_REGISTRY`,
  `STACK_IMAGE_REGISTRY_USER`, `STACK_IMAGE_REGISTRY_TOKEN`,
  `LETSENCRYPT_EMAIL`. `k8s-host.sh` provisions the host exactly the way that
  test provisions its cluster, so a working setup for one works for the other.

`record-quickstart.sh` only needs the registry variables and an existing host;
it never creates or destroys cloud resources.

## How the recording stays short

The animation has to be watchable in a README, so the recorder prepares state
off camera such that each recorded command still does real work but returns
quickly: the repo clone happens into a scratch `STACK_REPO_BASE_DIR`, the todo
image *tags* are dropped while Docker's layer cache is kept (so the recorded
build is genuine but takes seconds), and the images are pushed to the registry
in advance so the recorded `push-images` has nothing left to upload.

The waits that cannot be prepared away — the frontend's dev server coming up
under Docker, and on the cluster the pods becoming ready, the gateway routing
to them and, on a first deployment of a hostname, the ACME HTTP-01 exchange —
happen in `Hide` blocks. Each of those blocks ends with a `clear` *inside* the
block: `Hide` stops recording frames but the terminal still holds the line that
was typed, so without it the wait loop would sit on screen for the rest of the
recording.

Two details keep repeated takes cheap:

* The recorded `stack deploy` passes a fixed `--cluster` name. That name is the
  Kubernetes namespace, and the certificate Secret is named after it, so
  redeploying reuses the certificate cert-manager already holds instead of
  asking Let's Encrypt for a new one every take (see `remove_https_listener` in
  `src/stack/deploy/k8s/gateway.py`).
* The VM's node image cache and the registry both survive between takes.

## The tape is a template

The Kubernetes host's FQDN, its kubeconfig path, the image registry and the
host ports the Docker half curls are all decided outside the tape, so
`quickstart.tape` carries them as `@@...@@` placeholders.
`record-quickstart.sh` substitutes them into a rendered copy under
`/tmp/stack-demo` and runs vhs against that. Run vhs against the rendered copy,
not against `quickstart.tape` itself.

The ports are worked out by generating a throwaway Compose spec and reading the
mapped host ports out of it, rather than being written down anywhere — the todo
stack has moved its frontend and backend ports before, and a recording that
curls a stale port either prints a failure or, worse, quietly gets an answer
from something else. For the same reason the recorder refuses to start if
anything is already listening on one of those ports.
