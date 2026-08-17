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

The scheme syntax and its resolution live in stack.deploy.references, shared
with the spec's `secrets` section; this module keeps only what is specific to
the kubeconfig -- the bare-path meaning, and its materialization as a file for
the kubernetes client.
"""

from contextlib import contextmanager
from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp

from stack import constants
from stack.deploy import references


def reference_scheme(value):
    """The scheme of a kube-config value, or None if it is a bare path."""
    return references.reference_scheme(value)


def is_deferred_reference(value):
    """True if this value is resolved at connect time rather than copied in."""
    return references.is_reference(value)


def validate_reference(value):
    """Reject a kube-config value we would not be able to resolve.

    A bare path is valid -- it is the original meaning of the field -- so only a
    value carrying a scheme is checked.
    """
    references.validate_reference(value, constants.kube_config_key)


def resolve_reference(reference):
    """Return the kubeconfig content a deferred reference names."""
    return references.resolve_reference(reference, constants.kube_config_key)


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
