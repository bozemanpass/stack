# VHS tape for the README quick-start animation.
#
# Renders docs/images/quickstart.gif — a real, unfaked run of the quick start
# from README.md against the example todo stack: first to local Docker, then
# the same stack to a real Kubernetes cluster with a real hostname and a real
# Let's Encrypt certificate.
#
# Run it via ./demo/record-quickstart.sh, which prepares the caches this tape
# assumes and fills in the @@...@@ placeholders below from the Kubernetes host
# created by ./demo/k8s-host.sh. Because of those placeholders this file is a
# template: run `vhs` against the rendered copy the record script writes, not
# against this file.
#
# Requires: vhs, ttyd, ffmpeg, docker, jq, openssl, kubectl, and the `stack`
# CLI on PATH.

Output docs/images/quickstart.gif

Set Shell bash
Set FontSize 14
Set Width 1100
Set Height 640
Set Padding 18
Set Framerate 20
Set TypingSpeed 20ms
Set Theme "Catppuccin Mocha"

# --- off-camera setup ------------------------------------------------------
# Work in a scratch dir, with a scratch repo base dir, so the demo never
# collides with real clones or drops files in the repo. The `cd` and `export`
# apply to the recorded shell only; vhs resolves Output against its own cwd.
Hide
Type "cd /tmp/stack-demo && export STACK_REPO_BASE_DIR=/tmp/stack-demo/repos"
Enter
Type `PS1='\[\e[38;5;114m\]▸\[\e[0m\] '`
Enter
Type "clear"
Enter
Show

# --- clone and build -------------------------------------------------------
# Real clone (~2s) and a real container build (~8s, warm layer cache).
Type "stack fetch repo bozemanpass/example-todo-list"
Enter
Wait+Line@180s /^▸$/
Sleep 1s

# Show what the stack actually is before building it, so the rest of the
# recording has some context: three services, two built here, one stock
# postgres, and how requests reach them.
Type "stack chart --stack todo --format text"
Enter
Wait+Line@60s /^▸$/
Sleep 3s

# --quiet-build drops the docker build log, which is many screens of BuildKit
# step output that would swamp a short animation. It keeps the per-container
# progress lines. The README quick start deliberately shows the plain command;
# the flag is here only to keep the recording legible.
Type "stack prepare --stack todo --quiet-build"
Enter
Wait+Line@600s /^▸$/
Sleep 2s

Type "clear"
Enter

# --- confirm the build prerequisites are in place --------------------------
# Answers "did I already build the images?" without re-running a prepare that
# might take minutes — the question you have after stepping away from the build.
Type "stack check --stack todo"
Enter
Wait+Line@120s /^▸$/
Sleep 2s

# --- generate the deployment spec, then the deployment ---------------------
# Say out loud which target this half of the recording is for: the same stack
# is deployed to Kubernetes further down, and the two halves should be read as
# a pair.
Type "# first, deploy this stack to Docker on this laptop"
Enter
Sleep 2s

# init and deploy are near-instant and quiet, so pause a beat to let them be read.
Type "stack init --stack todo --output todo.yml --deploy-to compose --map-ports-to-host localhost-same"
Enter
Wait+Line@120s /^▸$/
Sleep 1s

Type "mkdir -p ~/deployments"
Enter
Wait+Line@60s /^▸$/

Type "stack deploy --spec-file todo.yml --deployment-dir ~/deployments/todo-demo"
Enter
Wait+Line@180s /^▸$/
Sleep 1500ms

Type "clear"
Enter

# --- run it ----------------------------------------------------------------
# ~12s: containers created, db comes up healthy, then the backend starts.
Type "stack manage --dir ~/deployments/todo-demo start"
Enter
Wait+Line@300s /^▸$/
Sleep 2500ms

# Off camera: the frontend's dev server needs a few seconds more after its
# container starts before it answers, which is dead air. The `clear` is inside
# the hidden block on purpose: Hide stops recording frames but the terminal
# still holds the typed line, so without it the wait loop would be on screen
# for the rest of the recording.
Hide
Type `for i in $(seq 60); do curl -sf -o /dev/null @@FRONTEND_URL@@ && break; sleep 2; done`
Enter
Wait+Line@180s /^▸$/
Type "clear"
Enter
Show

Type "stack manage --dir ~/deployments/todo-demo status"
Enter
Wait+Line@120s /^▸$/
Sleep 2s

# --- prove the whole system works, not just that a port answers ------------
# The web app is served on the host ports the spec asked for. Those ports come
# from the stack and have changed before, so record-quickstart.sh reads them out
# of a generated spec and substitutes them here — and refuses to record at all if
# anything else already holds them, so these really are the deployment answering.
Type `curl -s -o /dev/null -w "frontend HTTP %{http_code}\n" @@FRONTEND_URL@@`
Enter
Wait+Line@60s /^▸$/
Sleep 1500ms

# ...and the API is backed by a working database. The list starts empty
# because the recorder removes the deployment (and its db volume) each run.
Type "curl -s @@API_URL@@/ | jq -c ."
Enter
Wait+Line@60s /^▸$/
Sleep 2s

# The id comes back from postgres, so a successful round trip proves the
# backend and the database, not merely that the web server responded.
Type `curl -s -X POST @@API_URL@@/ \`
Enter
Type `  -H 'Content-Type: application/json' \`
Enter
Type `  -d '{"title":"Deploy without a PaaS"}' | jq -c '{id, title, completed}'`
Enter
Wait+Line@60s /^▸$/
Sleep 2500ms

# Tick it off, so the recording exercises a write that updates an existing row
# rather than only inserting one.
Type `curl -s -X PUT @@API_URL@@/1 \`
Enter
Type `  -H 'Content-Type: application/json' \`
Enter
Type `  -d '{"completed":true}' | jq -c '{id, title, completed}'`
Enter
Wait+Line@60s /^▸$/
Sleep 2s

Type `curl -s @@API_URL@@/ | jq -c '.[] | {id, title, completed}'`
Enter
Wait+Line@60s /^▸$/
Sleep 3s

# --- and tear down ---------------------------------------------------------
Type "stack manage --dir ~/deployments/todo-demo stop"
Enter
Wait+Line@180s /^▸$/
Sleep 3s

Type "clear"
Enter

# --- the same stack, on Kubernetes -----------------------------------------
# Nothing about the stack changes here: the same containers built above are
# pushed to a registry and run on a real single-node k3s cluster on a cloud VM
# (created out of band by ./demo/k8s-host.sh). Only the deployment spec differs.
Type "# now deploy the same stack to a Kubernetes cluster in the cloud"
Enter
Sleep 2s

# --http-proxy-fqdn is the cluster's hostname, so the deployment gets a real
# DNS name — and, from cert-manager on the cluster, a real Let's Encrypt
# certificate for it.
Type `stack init --stack todo --output todo-k8s.yml --deploy-to k8s \`
Enter
Type `  --kube-config @@KUBE_CONFIG@@ --image-registry @@IMAGE_REGISTRY@@ \`
Enter
Type `  --http-proxy-fqdn @@K8S_FQDN@@ \`
Enter
Type `  --config REACT_APP_API_URL=https://@@K8S_FQDN@@/api/todos`
Enter
Wait+Line@120s /^▸$/
Sleep 1s

Type "clear"
Enter

# A fixed cluster name means a redeployment lands in the same namespace, so
# cert-manager reuses the certificate it already holds instead of asking Let's
# Encrypt for another one on every take.
Type `stack deploy --cluster stack-todo-demo --spec-file todo-k8s.yml \`
Enter
Type `  --deployment-dir ~/deployments/todo-k8s`
Enter
Wait+Line@180s /^▸$/
Sleep 1500ms

# The cluster cannot see this laptop's image cache, so the images built earlier
# go to the registry named in the spec. Layers already pushed are skipped.
Type "stack manage --dir ~/deployments/todo-k8s push-images"
Enter
Wait+Line@900s /^▸$/
Sleep 1500ms

Type "clear"
Enter

# --- run it on the cluster -------------------------------------------------
Type "stack manage --dir ~/deployments/todo-k8s start"
Enter
Wait+Line@600s /^▸$/
Sleep 2500ms

# Off camera, as in the Docker half above: wait for the pods to become ready
# and the gateway to route to them, and — the first time this hostname is
# deployed — for the ACME HTTP-01 exchange to finish. That is real waiting, up
# to a minute or two, and it is all dead air.
Hide
Type `for i in $(seq 120); do curl -sf -o /dev/null https://@@K8S_FQDN@@/api/todos && break; sleep 5; done`
Enter
Wait+Line@700s /^▸$/
Type "clear"
Enter
Show

# status reports the certificate the cluster holds for this deployment, so the
# TLS line here is the certificate the curls below are about to use.
Type "stack manage --dir ~/deployments/todo-k8s status"
Enter
Wait+Line@300s /^▸$/
Sleep 3s

Type "clear"
Enter

# stack's own status output is deliberately target-agnostic, which can make the
# Kubernetes deployment look like it happened by magic. This is what it
# actually built: ordinary Deployments, Services and a Gateway API HTTPRoute in
# a namespace named for the deployment's cluster — nothing a `kubectl` user
# would find surprising, and all of it removed again by `stack manage stop`.
Type "export KUBECONFIG=@@KUBE_CONFIG@@"
Enter
Wait+Line@60s /^▸$/

Type "kubectl -n stack-todo-demo get pods,svc,httproute"
Enter
Wait+Line@120s /^▸$/
Sleep 4s

# And the other half of what the deployment asked the cluster for: cert-manager
# holding the Let's Encrypt certificate for this hostname, which is what the
# HTTPS requests below use.
Type "kubectl get certificate -A"
Enter
Wait+Line@120s /^▸$/
Sleep 3s

Type "clear"
Enter

# --- prove it, over HTTPS, from outside the cluster ------------------------
# No -k: curl verifying the chain is itself the proof that the certificate is
# real and publicly trusted.
Type `curl -s -o /dev/null -w "frontend HTTPS %{http_code}\n" https://@@K8S_FQDN@@`
Enter
Wait+Line@120s /^▸$/
Sleep 1500ms

Type `echo | openssl s_client -connect @@K8S_FQDN@@:443 2>/dev/null | openssl x509 -noout -issuer`
Enter
Wait+Line@120s /^▸$/
Sleep 2500ms

# Same round trip as the Docker half, through the cluster's proxy this time:
# the id comes back from postgres running in the cluster.
Type `curl -s -X POST https://@@K8S_FQDN@@/api/todos \`
Enter
Type `  -H 'Content-Type: application/json' \`
Enter
Type `  -d '{"title":"Same stack, no PaaS"}' | jq -c '{id, title, completed}'`
Enter
Wait+Line@120s /^▸$/
Sleep 2500ms

Type `curl -s -X PUT https://@@K8S_FQDN@@/api/todos/1 \`
Enter
Type `  -H 'Content-Type: application/json' \`
Enter
Type `  -d '{"completed":true}' | jq -c '{id, title, completed}'`
Enter
Wait+Line@120s /^▸$/
Sleep 2s

Type `curl -s https://@@K8S_FQDN@@/api/todos | jq -c '.[] | {id, title, completed}'`
Enter
Wait+Line@120s /^▸$/
Sleep 3s

# --- and tear down ---------------------------------------------------------
Type "stack manage --dir ~/deployments/todo-k8s stop"
Enter
Wait+Line@300s /^▸$/
Sleep 3s
