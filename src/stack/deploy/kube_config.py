# Copyright © 2026 Bozeman Pass, Inc.

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http:#www.gnu.org/licenses/>.

"""Where a k8s deployment's cluster credential comes from.

A deployment directory is a portable artifact, and is frequently a git
repository of its own, so a kubeconfig copied into it is a cluster credential
committed to git.  The spec's `kube-config` value is therefore a *reference*
rather than necessarily a path: it says where the credential is to be found at
the moment it is needed, so that the deployment can record where its credential
lives without recording the credential.

    kube-config: /home/me/.kube/config          bare path, copied in at create time
    kube-config: file:/etc/stack/kubeconfig.yml a path, read at connect time
    kube-config: env:KUBECONFIG_DATA            the variable holds the config itself
    kube-config: env-file:KUBECONFIG            the variable holds a path to it
    kube-config: exec:sops -d cluster.enc.yml   the command's stdout is the config

A bare path keeps the original behaviour -- the file is copied into the
deployment directory when the deployment is created -- because that is what
existing specs and deployments mean by it.  Every other form is deferred: the
deployment directory gets no kubeconfig at all, and the reference is resolved
each time the deployer connects.

`env:` is the form the CI case wants.  Holding a kubeconfig as a repository
secret and writing it into the deployment directory before running `stack
manage` puts the credential on the runner's disk, in the deployment, for the
life of the job; naming it from the spec instead means the job passes the
secret in the environment and the deployment stays credential-free.

`exec:` is the general escape hatch, and is what any secret store is reached
through until it is worth a scheme of its own -- `pass show`, `op read`,
`vault kv get`, `sops -d`, a cloud provider's CLI.  It runs through a shell, so
pipelines work; the command comes from the operator's own spec file, which is
the same trust level as the command line that created it.
"""

import os
import re
import subprocess

from contextlib import contextmanager
from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp

from stack import constants
from stack.log import log_debug
from stack.util import error_exit


# Only a leading lowercase scheme counts, so that ordinary paths -- which have no
# colon before their first slash -- are never mistaken for references.
_SCHEME_RE = re.compile(r"^([a-z][a-z0-9-]*):")

_SCHEMES = ("file", "env", "env-file", "exec")


def reference_scheme(value):
    """The scheme of a kube-config value, or None if it is a bare path."""
    if value is None:
        return None
    match = _SCHEME_RE.match(str(value))
    return match.group(1) if match else None


def is_deferred_reference(value):
    """True if this value is resolved at connect time rather than copied in."""
    return reference_scheme(value) is not None


def validate_reference(value):
    """Reject a kube-config value we would not be able to resolve.

    Called where the reference is recorded rather than where it is used, so that
    a mistyped scheme is caught by `init` and `deploy` rather than at connect
    time on a CI runner.  The reference is deliberately not resolved here: the
    credential it names is quite legitimately absent on the machine that creates
    the deployment, which is the whole point of deferring it.
    """
    scheme = reference_scheme(value)
    if scheme is None:
        return
    if scheme not in _SCHEMES:
        error_exit(
            f"{constants.kube_config_key} '{value}' has an unknown scheme '{scheme}:'"
            f" (expected one of: {', '.join(s + ':' for s in _SCHEMES)}, or a path)"
        )
    if not str(value)[len(scheme) + 1 :].strip():
        error_exit(f"{constants.kube_config_key} '{value}' names nothing after '{scheme}:'")


def _read_file(path: Path, reference):
    if not path.exists():
        error_exit(f"{constants.kube_config_key} is '{reference}' but {path} does not exist")
    return path.read_text()


def _run_command(command, reference):
    log_debug(f"Resolving {constants.kube_config_key} with: {command}")
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        # The command's own stderr is the only useful diagnostic here, and it is
        # captured, so it has to be carried into the error to be seen at all.
        error_exit(
            f"{constants.kube_config_key} command exited {result.returncode}: {command}\n{result.stderr.strip()}"
        )
    if not result.stdout.strip():
        error_exit(f"{constants.kube_config_key} command '{command}' produced no output")
    return result.stdout


def resolve_reference(reference):
    """Return the kubeconfig content a deferred reference names."""
    scheme, _, rest = str(reference).partition(":")
    if scheme == "env":
        content = os.environ.get(rest)
        if content is None:
            error_exit(f"{constants.kube_config_key} is '{reference}' but ${rest} is not set in the environment")
        if not content.strip():
            error_exit(f"{constants.kube_config_key} is '{reference}' but ${rest} is empty")
        return content
    if scheme == "env-file":
        path = os.environ.get(rest)
        if not path:
            error_exit(f"{constants.kube_config_key} is '{reference}' but ${rest} is not set in the environment")
        return _read_file(Path(path).expanduser(), reference)
    if scheme == "file":
        return _read_file(Path(rest).expanduser(), reference)
    if scheme == "exec":
        return _run_command(rest, reference)
    # validate_reference runs at init and deploy, so reaching this means a spec
    # file was edited by hand after the fact.
    error_exit(f"{constants.kube_config_key} '{reference}' has an unknown scheme '{scheme}:'")


@contextmanager
def kube_config_file(spec, deployment_dir: Path):
    """Yield a path to a kubeconfig file for this deployment.

    A bare path was copied into the deployment directory at create time, so that
    file is the answer.  A deferred reference is resolved here and materialized
    into a private temporary directory that is removed on the way out, so the
    credential is on disk only for as long as the kubernetes client takes to
    read it -- it has to be a file at all only because load_kube_config takes a
    path rather than content.

    One consequence of the temporary location: a deferred kubeconfig that refers
    to certificate files by *relative* path would resolve them against that
    directory rather than anywhere useful.  Embedded (`-data`) certificates,
    which is what k3s and every cloud provider emit, are unaffected.
    """
    reference = spec.get_kube_config() if spec else None
    if not is_deferred_reference(reference):
        yield deployment_dir.joinpath(constants.kube_config_filename)
        return

    temp_dir = Path(mkdtemp(prefix="stack-kubeconfig-"))
    try:
        path = temp_dir.joinpath(constants.kube_config_filename)
        # mkdtemp is already 0700; the file mode states the same intent locally.
        path.touch(mode=0o600)
        path.write_text(resolve_reference(reference))
        yield path
    finally:
        rmtree(temp_dir, ignore_errors=True)
