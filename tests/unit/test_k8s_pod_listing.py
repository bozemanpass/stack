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

"""Which pods the deployment commands report.

A pod that has been deleted is still listed by the API until its containers have
stopped, which on a real cluster is a graceful shutdown lasting tens of seconds.
Reporting it means "ps" and "status" describe a container that is on its way out,
and "logs" replays output from before a restart -- which is exactly how a stopped
and restarted deployment came to look like it had already finished its work.
"""

from types import SimpleNamespace

from stack.deploy.k8s.helpers import live_pods, pods_in_deployment

NAMESPACE = "stack-test"


def pod(name, terminating=False):
    """Stands in for a V1Pod; only the metadata is read here."""
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, namespace=NAMESPACE, deletion_timestamp="2026-08-13T23:54:05Z" if terminating else None)
    )


def fake_api(pods):
    return SimpleNamespace(list_namespaced_pod=lambda **kwargs: SimpleNamespace(items=pods))


def test_live_pods_keeps_pods_that_are_not_being_deleted():
    pods = [pod("deploy-web-new"), pod("deploy-web-old", terminating=True)]

    assert [p.metadata.name for p in live_pods(pods)] == ["deploy-web-new"]


def test_live_pods_of_nothing_is_nothing():
    assert live_pods([]) == []


def test_all_pods_terminating_reports_none():
    # Mid-stop every pod is on its way out, and the deployment has nothing to
    # report rather than a list of containers that are already going away.
    pods = [pod("deploy-web", terminating=True), pod("deploy-db", terminating=True)]

    assert live_pods(pods) == []


def test_pods_in_deployment_skips_a_terminating_pod():
    # The listing that logs and exec work from: a restart leaves the old pod
    # present for a while, and its log still holds everything from before.
    api = fake_api([pod("deploy-web-old", terminating=True), pod("deploy-web-new")])

    assert pods_in_deployment(api, "deploy", NAMESPACE) == ["deploy-web-new"]
