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

"""Write-conflict handling in "stack manage update" on a k8s deployment.

No cluster is involved: the API is stubbed.  What is under test is the
read-modify-write cycle in K8sDeployer.update(): the PATCH sends back a
Deployment read earlier, so its resourceVersion is stale by the time it is
written, and the API server answers 409 whenever anything -- the deployment
controller updating status is enough -- touched the object in between.  A
conflict must be re-read and re-applied, not raised: raising is how a routine
`manage update` on kind died mid-way, since the image reload sits inside that
read-to-write window and each patch sets off a rollout that widens it for the
next.
"""

from types import SimpleNamespace

import pytest
from kubernetes import client

from stack.deploy.k8s import deploy_k8s
from stack.deploy.k8s.deploy_k8s import K8sDeployer

NAMESPACE = "stack-test"


def make_deployment(image):
    return client.V1Deployment(
        metadata=client.V1ObjectMeta(name="deploy-web"),
        spec=client.V1DeploymentSpec(
            selector=client.V1LabelSelector(match_labels={"app": "deploy"}),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(),
                spec=client.V1PodSpec(containers=[client.V1Container(name="web", image=image)]),
            ),
        ),
    )


class StubAppsApi:
    """Serves one live Deployment; PATCH conflicts a set number of times.

    A fresh read hands back a new object with the original content, the way a
    real conflict looks when the interfering write only touched status: the
    convergence still has to be applied to it.
    """

    def __init__(self, conflicts=0):
        self.live = make_deployment("app:old")
        self.conflicts = conflicts
        self.patched = []
        self.reads = 0

    def list_namespaced_deployment(self, namespace):
        return SimpleNamespace(items=[self.live])

    def read_namespaced_deployment(self, name, namespace):
        self.reads += 1
        return make_deployment("app:old")

    def patch_namespaced_deployment(self, name, namespace, body):
        if self.conflicts > 0:
            self.conflicts -= 1
            raise client.exceptions.ApiException(status=409, reason="Conflict")
        self.patched.append(body)


@pytest.fixture
def deployer(monkeypatch):
    """A K8sDeployer whose deployment directory wants one image change applied.

    Built without __init__, as in test_k8s_logs.py; update() only reaches for
    the attributes set here.  The registry is set so the kind image-reload
    branch is skipped, and the staged-image scan is stubbed out.
    """
    monkeypatch.setattr(deploy_k8s, "stale_staged_images", lambda image_set, registry, deployment_id: [])

    deployer = object.__new__(K8sDeployer)
    deployer.connect_api = lambda: None
    deployer.k8s_namespace = NAMESPACE
    deployer.is_kind = lambda: False
    deployer._create_secrets = lambda: False
    deployer.cluster_info = SimpleNamespace(
        app_name="deploy",
        image_set=set(),
        spec=SimpleNamespace(get_image_registry=lambda: "registry.example.com/org"),
        get_deployments=lambda image_pull_policy=None: [make_deployment("app:new")],
    )
    return deployer


def run_update(deployer, conflicts):
    api = StubAppsApi(conflicts=conflicts)
    deployer.apps_api = api
    deployer.update()
    return api


def test_conflict_is_retried_against_a_fresh_read(deployer):
    api = run_update(deployer, conflicts=1)

    assert api.reads == 1
    # The re-applied convergence reaches the cluster: the retried body carries
    # the image change, not just the fresh read.
    assert len(api.patched) == 1
    assert api.patched[0].spec.template.spec.containers[0].image == "app:new"


def test_conflict_free_update_patches_once(deployer):
    api = run_update(deployer, conflicts=0)

    assert api.reads == 0
    assert len(api.patched) == 1
    assert api.patched[0].spec.template.spec.containers[0].image == "app:new"


def test_persistent_conflict_is_raised(deployer):
    # A conflict on every attempt means something is fighting the update for
    # real; that is worth a failure rather than an infinite retry.
    with pytest.raises(client.exceptions.ApiException) as excinfo:
        run_update(deployer, conflicts=3)

    assert excinfo.value.status == 409


def test_other_api_errors_are_not_retried(deployer):
    api = StubAppsApi()

    def forbid(name, namespace, body):
        raise client.exceptions.ApiException(status=403, reason="Forbidden")

    api.patch_namespaced_deployment = forbid
    deployer.apps_api = api

    with pytest.raises(client.exceptions.ApiException) as excinfo:
        deployer.update()

    assert excinfo.value.status == 403
    assert api.reads == 0
