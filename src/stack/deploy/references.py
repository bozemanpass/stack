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

"""Values that are references to a credential rather than the credential itself.

A deployment artifact is frequently committed to git, so anywhere it needs a
secret it records a *reference* saying where the secret is to be found at the
moment it is needed:

    file:/etc/stack/kubeconfig.yml   a path, read at resolve time
    env:KUBECONFIG_DATA              the variable holds the content itself
    env-file:KUBECONFIG              the variable holds a path to it
    exec:sops -d cluster.enc.yml     the command's stdout is the content

This module is the scheme syntax and its resolution, shared by every field that
uses it (the spec's `kube-config`, the spec's `secrets`).  What a value with no
scheme means -- a bare path, a generated secret -- differs per field and stays
with the field's own code; the `what` argument carried through these functions
names the field in error messages, so that a failure on a CI runner says which
value it was resolving.

`exec:` is the general escape hatch, and is what any secret store is reached
through until it is worth a scheme of its own -- `pass show`, `op read`,
`vault kv get`, `sops -d`, a cloud provider's CLI.  It runs through a shell, so
pipelines work; the command comes from the operator's own spec file, which is
the same trust level as the command line that created it.
"""

import os
import re
import subprocess

from pathlib import Path

from stack.log import log_debug
from stack.util import error_exit


# Only a leading lowercase scheme counts, so that ordinary paths -- which have no
# colon before their first slash -- are never mistaken for references.
_SCHEME_RE = re.compile(r"^([a-z][a-z0-9-]*):")

SCHEMES = ("file", "env", "env-file", "exec")


def reference_scheme(value):
    """The scheme of a value, or None if it carries no scheme."""
    if value is None:
        return None
    match = _SCHEME_RE.match(str(value))
    return match.group(1) if match else None


def is_reference(value):
    """True if this value is resolved at the moment it is needed."""
    return reference_scheme(value) is not None


def validate_reference(value, what, bare_meaning="a path"):
    """Reject a value we would not be able to resolve.

    Called where the reference is recorded rather than where it is used, so that
    a mistyped scheme is caught by `init` and `deploy` rather than at the point
    of use on a CI runner.  The reference is deliberately not resolved here: the
    secret it names is quite legitimately absent on the machine that creates
    the deployment, which is the whole point of deferring it.

    A value with no scheme is not this module's to judge -- what it means
    (`bare_meaning`) belongs to the field -- so it passes untouched.
    """
    scheme = reference_scheme(value)
    if scheme is None:
        return
    if scheme not in SCHEMES:
        error_exit(
            f"{what} '{value}' has an unknown scheme '{scheme}:'"
            f" (expected one of: {', '.join(s + ':' for s in SCHEMES)}, or {bare_meaning})"
        )
    if not str(value)[len(scheme) + 1 :].strip():
        error_exit(f"{what} '{value}' names nothing after '{scheme}:'")


def _read_file(path: Path, reference, what):
    if not path.exists():
        error_exit(f"{what} is '{reference}' but {path} does not exist")
    return path.read_text()


def _run_command(command, what):
    log_debug(f"Resolving {what} with: {command}")
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        # The command's own stderr is the only useful diagnostic here, and it is
        # captured, so it has to be carried into the error to be seen at all.
        error_exit(f"{what} command exited {result.returncode}: {command}\n{result.stderr.strip()}")
    if not result.stdout.strip():
        error_exit(f"{what} command '{command}' produced no output")
    return result.stdout


def resolve_reference(reference, what):
    """Return the content a reference names."""
    scheme, _, rest = str(reference).partition(":")
    if scheme == "env":
        content = os.environ.get(rest)
        if content is None:
            error_exit(f"{what} is '{reference}' but ${rest} is not set in the environment")
        if not content.strip():
            error_exit(f"{what} is '{reference}' but ${rest} is empty")
        return content
    if scheme == "env-file":
        path = os.environ.get(rest)
        if not path:
            error_exit(f"{what} is '{reference}' but ${rest} is not set in the environment")
        return _read_file(Path(path).expanduser(), reference, what)
    if scheme == "file":
        return _read_file(Path(rest).expanduser(), reference, what)
    if scheme == "exec":
        return _run_command(rest, what)
    # validate_reference runs where the reference was recorded, so reaching this
    # means the file holding it was edited by hand after the fact.
    error_exit(f"{what} '{reference}' has an unknown scheme '{scheme}:'")
