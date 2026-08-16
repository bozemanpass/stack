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

"""What the deployment commands do when the kind cluster is gone.

Stopping a kind deployment deletes its whole cluster, so between a stop and the
next start there is no kube context to load -- which is the ordinary resting
state of a stopped deployment, not a fault.  Asking one what it is running used
to raise the kubernetes client's ConfigException straight out of the CLI: the
app-deploy test printed a traceback on every kind run, and passed anyway,
because a crashing `ps` writes nothing to stdout and the wait-for-stopped loop
read that silence as "stopped".

No cluster is involved here: connect_api is driven directly against a kube
config that has no such context.
"""

import pytest

from kubernetes.config.config_exception import ConfigException

from stack.deploy.deployer import ClusterNotRunningException, DeployerException
from stack.deploy.k8s.deploy_k8s import K8sDeployer


def stopped_kind_deployer():
    """A kind deployer whose cluster is not there.

    The constructor returns early without a deployment context (its own
    documented workaround), so the attributes connect_api reads are set here.
    """
    deployer = K8sDeployer(
        type="k8s-kind",
        deployment_context=None,
        compose_files=None,
        compose_project_name=None,
        compose_env_file=None,
    )
    deployer.kind_cluster_name = "stack-fc64341deea8dc77"
    return deployer


@pytest.fixture(autouse=True)
def no_kube_config(monkeypatch):
    """Fail every load_kube_config, as a deleted cluster does."""
    def raise_config_exception(**kwargs):
        raise ConfigException(
            f"Invalid kube-config file. Expected object with name {kwargs.get('context')} in contexts list"
        )

    monkeypatch.setattr("stack.deploy.k8s.deploy_k8s.config.load_kube_config", raise_config_exception)


def test_connect_api_reports_a_missing_kind_cluster_as_not_running():
    # Not the kubernetes client's ConfigException, which reads as a broken
    # config file rather than an absent cluster, and which nothing catches.
    with pytest.raises(ClusterNotRunningException) as raised:
        stopped_kind_deployer().connect_api()

    assert "stack-fc64341deea8dc77" in str(raised.value)


def test_cluster_not_running_is_a_deployer_exception():
    # So a caller that handles the general case still handles this one.
    assert issubclass(ClusterNotRunningException, DeployerException)


def test_ps_of_a_stopped_kind_deployment_is_empty():
    # An empty list is what the ps command prints "No containers running" for.
    assert stopped_kind_deployer().ps() == []


def test_status_of_a_stopped_kind_deployment_reports_nothing():
    assert stopped_kind_deployer().status() is None
