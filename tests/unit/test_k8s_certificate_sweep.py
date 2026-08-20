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

"""Tests for the certificate Secret lifecycle on a Gateway-provisioned cluster.

A certificate outlives the deployment that caused it on purpose: deleting one
that a redeployment could have reused is how a hostname reaches Let's Encrypt's
duplicate-certificate limit (#283).  So the property under test is mostly a
negative one -- what the sweep refuses to delete -- with deletion reserved for a
certificate that has been unreferenced long enough to have expired.

No cluster is involved: the API objects are stand-ins that record what the sweep
asked for.
"""

import datetime

import pytest

from types import SimpleNamespace

from stack.deploy.k8s import gateway


HOST = "app.example.com"
SECRET = gateway.secret_name_for_host(HOST)
LISTENER = gateway.listener_name_for_host(HOST)

NOW = datetime.datetime(2026, 8, 20, tzinfo=datetime.timezone.utc)


def stamp(days_ago):
    return (NOW - datetime.timedelta(days=days_ago)).isoformat()


class FakeApiException(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__(f"status {status}")


@pytest.fixture(autouse=True)
def api_exception(monkeypatch):
    """Let the stand-ins raise the exception type gateway.py catches."""
    monkeypatch.setattr(gateway.client.exceptions, "ApiException", FakeApiException)


def secret(name, unreferenced_since=None):
    annotations = {gateway.UNREFERENCED_SINCE_ANNOTATION: unreferenced_since} if unreferenced_since else None
    return SimpleNamespace(metadata=SimpleNamespace(name=name, annotations=annotations))


class FakeCoreApi:
    def __init__(self, secrets):
        self.secrets = secrets
        self.patched = {}
        self.deleted = []

    def list_namespaced_secret(self, namespace, field_selector=None):
        assert namespace == gateway.GATEWAY_NAMESPACE
        # The sweep asks only for TLS Secrets; anything else in kube-system is
        # none of its business.
        assert field_selector == "type=kubernetes.io/tls"
        return SimpleNamespace(items=self.secrets)

    def patch_namespaced_secret(self, name, namespace, body):
        self.patched[name] = body["metadata"]["annotations"][gateway.UNREFERENCED_SINCE_ANNOTATION]

    def delete_namespaced_secret(self, name, namespace):
        if name not in [s.metadata.name for s in self.secrets]:
            raise FakeApiException(404)
        self.deleted.append(name)


class FakeCustomObjApi:
    def __init__(self, listeners):
        self.listeners = listeners

    def get_namespaced_custom_object(self, group, version, namespace, plural, name):
        return {"spec": {"listeners": self.listeners}}


def https_listener(host):
    return gateway.https_listener_for_host(host)


def sweep(secrets, listeners, now=NOW):
    core_api = FakeCoreApi(secrets)
    deleted = gateway.sweep_certificate_secrets(core_api, FakeCustomObjApi(listeners), now=now)
    return core_api, deleted


def test_an_unreferenced_certificate_is_marked_before_it_is_deleted():
    # Nothing is deleted on first sight: the sweep does not know how long this
    # one has been idle, so it starts the clock and comes back later.
    core_api, deleted = sweep([secret(SECRET)], listeners=[])

    assert deleted == []
    assert core_api.deleted == []
    assert core_api.patched[SECRET] == NOW.isoformat()


def test_a_certificate_unreferenced_past_its_lifetime_is_deleted():
    core_api, deleted = sweep([secret(SECRET, stamp(days_ago=91))], listeners=[])

    assert deleted == [SECRET]
    assert core_api.deleted == [SECRET]


def test_a_certificate_unreferenced_but_still_valid_is_kept():
    # Still inside a certificate's lifetime, so redeploying this hostname would
    # reuse it -- which is the whole reason the Secret survives a destroy.
    core_api, deleted = sweep([secret(SECRET, stamp(days_ago=30))], listeners=[])

    assert deleted == []
    assert core_api.deleted == []
    # And the mark is left as it was, so the interval keeps running.
    assert core_api.patched == {}


def test_a_referenced_certificate_is_never_deleted_however_old_its_mark():
    # A hostname served again keeps its certificate: a stale mark from an
    # earlier idle spell must not condemn a certificate now in use.
    core_api, deleted = sweep([secret(SECRET, stamp(days_ago=400))], listeners=[https_listener(HOST)])

    assert deleted == []
    assert core_api.deleted == []


def test_certificates_stack_did_not_name_are_left_alone():
    # A machine-provisioned wildcard certificate lives in the same namespace and
    # is not stack's to collect.
    core_api, deleted = sweep([secret("wildcard-example-com-tls", stamp(days_ago=400))], listeners=[])

    assert deleted == []
    assert core_api.deleted == []
    assert core_api.patched == {}


def test_an_unreadable_mark_restarts_the_interval_rather_than_deleting():
    core_api, deleted = sweep([secret(SECRET, "last tuesday")], listeners=[])

    assert deleted == []
    assert core_api.patched[SECRET] == NOW.isoformat()


def test_nothing_is_swept_without_a_gateway():
    class NoGateway:
        def get_namespaced_custom_object(self, **kwargs):
            raise FakeApiException(404)

    core_api = FakeCoreApi([secret(SECRET, stamp(days_ago=400))])
    assert gateway.sweep_certificate_secrets(core_api, NoGateway(), now=NOW) == []
    assert core_api.deleted == []


def test_serving_a_hostname_again_clears_its_mark():
    core_api = FakeCoreApi([secret(SECRET, stamp(days_ago=30))])
    gateway.clear_unreferenced_mark(core_api, HOST)

    assert core_api.patched[SECRET] is None


def test_clearing_the_mark_tolerates_a_hostname_with_no_certificate_yet():
    # First deployment of a hostname, or one covered by a wildcard listener:
    # there is no Secret of its own to annotate.
    class Missing(FakeCoreApi):
        def patch_namespaced_secret(self, name, namespace, body):
            raise FakeApiException(404)

    gateway.clear_unreferenced_mark(Missing([]), HOST)


def test_deleting_a_certificate_reports_whether_there_was_one():
    core_api = FakeCoreApi([secret(SECRET)])
    assert gateway.delete_certificate_secret(core_api, HOST) is True
    assert core_api.deleted == [SECRET]

    assert gateway.delete_certificate_secret(FakeCoreApi([]), HOST) is False


def test_the_listener_and_its_secret_agree_on_the_hostname():
    # The sweep's "is it referenced?" test compares the listener's certificateRef
    # against the Secret name, so the two namings have to stay in step.
    assert https_listener(HOST)["tls"]["certificateRefs"] == [{"name": SECRET}]
    assert https_listener(HOST)["name"] == LISTENER
