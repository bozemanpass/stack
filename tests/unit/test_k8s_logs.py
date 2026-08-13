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

"""Log collection for "stack manage logs" on a k8s deployment.

No cluster is involved: the pod listing and the log reads are stubbed, since what
is under test is how the deployer handles what the API hands back.
"""

from types import SimpleNamespace

import pytest

from stack.deploy.k8s import deploy_k8s
from stack.deploy.k8s.deploy_k8s import K8sDeployer

NAMESPACE = "stack-test"
POD = "deploy-web-abc123"


@pytest.fixture
def deployer(monkeypatch):
    """A K8sDeployer wired to one pod with one container, and no cluster behind it.

    Built without __init__, which would want a deployment directory and a real
    connection; logs() only reaches for the attributes set here.
    """
    monkeypatch.setattr(deploy_k8s, "pods_in_deployment", lambda api, app_name, namespace: [POD])
    monkeypatch.setattr(deploy_k8s, "containers_in_pod", lambda api, pod_name, namespace: ["web"])

    deployer = object.__new__(K8sDeployer)
    deployer.connect_api = lambda: None
    deployer.k8s_namespace = NAMESPACE
    deployer.cluster_info = SimpleNamespace(app_name="deploy")
    return deployer


def read_logs(deployer):
    """Drain the generator logs() returns, back into the text it carries."""
    return b"".join(chunk for _, chunk in deployer.logs(services=None, tail=None, follow=False, stream=True)).decode()


def set_log_response(deployer, response):
    deployer.core_api = SimpleNamespace(read_namespaced_pod_log=lambda *args, **kwargs: response)


def test_container_log_lines_are_labelled(deployer):
    set_log_response(deployer, "first line\nsecond line")

    assert read_logs(deployer) == "web: first line\nweb: second line\n"


def test_container_with_no_output_yet_is_not_an_error(deployer):
    # The kubernetes client deserializes an empty response body to None, not "".
    # A container that is running but has yet to write anything is an ordinary
    # state -- against a real cluster, anything polling for a log line hits it
    # while the image is still being pulled -- and used to raise AttributeError:
    # 'NoneType' object has no attribute 'splitlines', killing the caller.
    set_log_response(deployer, None)

    assert read_logs(deployer) == ""


def test_api_failure_reports_no_logs_available(deployer):
    # A pod that has not started yet fails the request outright; that is already
    # handled, and is a different case from a started pod with an empty log.
    def raise_api_exception(*args, **kwargs):
        raise deploy_k8s.client.exceptions.ApiException(status=400, reason="container not created")

    deployer.core_api = SimpleNamespace(read_namespaced_pod_log=raise_api_exception)

    assert "No logs available" in read_logs(deployer)
