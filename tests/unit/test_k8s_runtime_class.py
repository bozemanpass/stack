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

"""Tests for the runtime-class spec key, which puts pods on a sandboxed runtime.

The cluster side of this cannot be tested here or on kind -- a RuntimeClass such as
kata needs a runtime installed on the nodes -- so what is asserted is that the right
pods, and only those, name the class in what goes to the API.
"""

import pytest

from conftest import k8s_dict, make_cluster_info


TWO_SERVICE_POD = """\
    services:
      web:
        image: nginx:local
        ports:
          - "80"
      db:
        image: postgres:local
    """


def spec_with(runtime_class, **overrides):
    spec = {
        "stack": "teststack",
        "deploy-to": "k8s",
        "image-registry": "registry.example.com/org",
    }
    if runtime_class is not None:
        spec["runtime-class"] = runtime_class
    spec.update(overrides)
    return spec


def runtime_classes(tmp_path, spec_obj):
    """Map of service name to the runtime class its Deployment names (None if unset)."""
    cluster_info = make_cluster_info(tmp_path, TWO_SERVICE_POD, spec_obj)
    ret = {}
    for deployment in cluster_info.get_deployments():
        pod_spec = k8s_dict(deployment)["spec"]["template"]["spec"]
        service = k8s_dict(deployment)["spec"]["template"]["metadata"]["labels"]["service"]
        ret[service] = pod_spec.get("runtimeClassName")
    return ret


def test_no_runtime_class_leaves_the_cluster_default(tmp_path):
    # Absent rather than empty: a runtimeClassName of "" is not the same request.
    assert runtime_classes(tmp_path, spec_with(None)) == {"web": None, "db": None}


def test_named_service_runs_under_the_class(tmp_path):
    classes = runtime_classes(tmp_path, spec_with({"services": {"web": "kata"}}))
    assert classes == {"web": "kata", "db": None}


def test_default_applies_to_every_service(tmp_path):
    classes = runtime_classes(tmp_path, spec_with({"default": "kata"}))
    assert classes == {"web": "kata", "db": "kata"}


def test_service_entry_overrides_the_default(tmp_path):
    classes = runtime_classes(tmp_path, spec_with({"default": "kata", "services": {"db": "gvisor"}}))
    assert classes == {"web": "kata", "db": "gvisor"}


def test_empty_service_entry_opts_out_of_the_default(tmp_path):
    # The reason for per-service granularity in the first place: a stack wanting a VM
    # around the service running untrusted code does not want one around its database.
    classes = runtime_classes(tmp_path, spec_with({"default": "kata", "services": {"db": None}}))
    assert classes == {"web": "kata", "db": None}


# ---------------------------------------------------------------------------
# Validation at deployment create time
# ---------------------------------------------------------------------------


def _check(spec_obj):
    from stack.deploy.deployment_create import _check_runtime_class
    from stack.deploy.spec import Spec

    _check_runtime_class(Spec(obj=spec_obj))


def test_rejected_on_a_compose_target(tmp_path):
    # Rejected rather than ignored: a spec that asked for isolation and silently got
    # an ordinary container looks exactly like one that worked.
    with pytest.raises(Exception, match="not supported for deployment type"):
        _check(spec_with({"default": "kata"}, **{"deploy-to": "compose"}))


def test_accepted_on_kind(tmp_path):
    # Nothing is wrong with the request on kind; whether the cluster has the class
    # installed is the cluster's answer to give.
    _check(spec_with({"default": "kata"}, **{"deploy-to": "k8s-kind"}))


def test_unknown_key_is_rejected(tmp_path):
    with pytest.raises(Exception, match="Unknown key"):
        _check(spec_with({"defualt": "kata"}))


def test_scalar_form_is_rejected(tmp_path):
    with pytest.raises(Exception, match="must be a mapping"):
        _check(spec_with("kata"))


def test_non_string_class_is_rejected(tmp_path):
    with pytest.raises(Exception, match="must be a string"):
        _check(spec_with({"services": {"web": True}}))


def test_privileged_and_sandboxed_is_rejected(tmp_path):
    # Inside a guest VM the host privileges asked for are not the host's, so the
    # combination is a mistake worth catching before it is debugged from inside.
    with pytest.raises(Exception, match="cannot be both privileged"):
        _check(spec_with({"services": {"web": "kata"}}, security={"web": {"privileged": "true"}}))


def test_privileged_service_that_opted_out_is_fine(tmp_path):
    _check(spec_with({"default": "kata", "services": {"web": None}}, security={"web": {"privileged": "true"}}))
