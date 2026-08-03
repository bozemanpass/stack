# VHS tape for the README quick-start animation.
#
# Renders docs/images/quickstart.gif — a real, unfaked run of the Docker quick
# start from README.md against the example todo stack.
#
# Run it via ./demo/record-quickstart.sh, which prepares the caches this tape
# assumes. Running `vhs demo/quickstart.tape` directly will still work, but the
# build and clone steps may take minutes instead of seconds.
#
# Requires: vhs, ttyd, ffmpeg, docker, and the `stack` CLI on PATH.

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
# init and deploy are near-instant and quiet, so pause a beat to let them be read.
Type "stack init --stack todo --output todo.yml --deploy-to compose --map-ports-to-host localhost-same"
Enter
Wait+Line@120s /^▸$/
Sleep 1s

# The whole generated spec is only 20 lines, so show all of it: the proxy
# routes, the host port mappings and the db volume are the interesting part.
Type "cat todo.yml"
Enter
Wait+Line@60s /^▸$/
Sleep 2500ms

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
Sleep 1500ms

Type "stack manage --dir ~/deployments/todo-demo status"
Enter
Wait+Line@120s /^▸$/
Sleep 2s

# --- prove the whole system works, not just that a port answers ------------
# The web app is served...
Type `curl -s -o /dev/null -w "frontend HTTP %{http_code}\n" localhost:3000`
Enter
Wait+Line@60s /^▸$/
Sleep 1500ms

# ...and the API is backed by a working database. The list starts empty
# because the recorder removes the deployment (and its db volume) each run.
Type "curl -s localhost:5000/ | jq -c ."
Enter
Wait+Line@60s /^▸$/
Sleep 2s

# The id comes back from postgres, so a successful round trip proves the
# backend and the database, not merely that the web server responded.
Type `curl -s -X POST localhost:5000/ \`
Enter
Type `  -H 'Content-Type: application/json' \`
Enter
Type `  -d '{"title":"Deploy without a PaaS"}' | jq -c '{id, title, completed}'`
Enter
Wait+Line@60s /^▸$/
Sleep 2500ms

Type `curl -s localhost:5000/ | jq -c '.[] | {id, title, completed}'`
Enter
Wait+Line@60s /^▸$/
Sleep 3s

# --- and tear down ---------------------------------------------------------
Type "stack manage --dir ~/deployments/todo-demo stop"
Enter
Wait+Line@180s /^▸$/
Sleep 3s
