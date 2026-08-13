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

"""Where a deployment's volume data is placed, per deployment target.

Compose and kind both keep it in ./data/<volume> under the deployment directory --
for kind by bind mounting that directory into the cluster's node, so the data
outlives the cluster, which stopping a kind deployment deletes. A remote cluster
cannot hold its data here, so its volumes are left unmapped and become PVCs from
the cluster's default storage class.

Regression coverage: kind used to be lumped in with the remote case and got an
unmapped volume, so a stop/start silently emptied the deployment's database.
"""

import yaml

from conftest import k8s_dict, make_cluster_info, make_stack_from_compose, run_stack

VOLUME_POD = """\
    services:
      web:
        image: nginx:local
        volumes:
          - db-data:/var/lib/data
    volumes:
      db-data:
    """


def init_spec(stack_dir, output_file, env, deploy_to):
    args = [
        "init",
        "--stack",
        str(stack_dir),
        "--output",
        str(output_file),
    ]
    if deploy_to:
        args += ["--deploy-to", deploy_to]
    if deploy_to == "k8s":
        args += ["--kube-config", "placeholder"]
    result = run_stack(args, env)
    assert result.returncode == 0, result.stderr
    return yaml.safe_load(output_file.read_text())


def volume_stack(tmp_path):
    return make_stack_from_compose(tmp_path, VOLUME_POD)


def test_compose_volume_is_mapped_into_the_deployment(tmp_path, isolated_env):
    spec = init_spec(volume_stack(tmp_path), tmp_path / "spec.yml", isolated_env, "compose")
    assert spec["volumes"] == {"db-data": "./data/db-data"}


def test_kind_volume_is_mapped_into_the_deployment(tmp_path, isolated_env):
    # The point of the regression: kind gets the same treatment as compose, so the
    # data survives the cluster being deleted and recreated by a stop/start.
    spec = init_spec(volume_stack(tmp_path), tmp_path / "spec.yml", isolated_env, "k8s-kind")
    assert spec["volumes"] == {"db-data": "./data/db-data"}


def test_remote_k8s_volume_is_left_for_the_cluster_to_provision(tmp_path, isolated_env):
    spec = init_spec(volume_stack(tmp_path), tmp_path / "spec.yml", isolated_env, "k8s")
    assert spec["volumes"] == {"db-data": None}


def kind_spec(**overrides):
    spec = {"stack": "teststack", "deploy-to": "k8s-kind"}
    spec.update(overrides)
    return spec


def test_kind_binds_a_relative_volume_path(tmp_path):
    # A kind PV's host path is derived from the volume name, not from the spec, so a
    # relative path in the spec is no obstacle to creating it. Without the PV the PVC
    # never binds and the pod stays Pending.
    cluster_info = make_cluster_info(tmp_path, VOLUME_POD, kind_spec(volumes={"db-data": "./data/db-data"}))

    pvs = [k8s_dict(pv) for pv in cluster_info.get_pvs()]
    assert len(pvs) == 1
    assert pvs[0]["spec"]["hostPath"]["path"] == "/mnt/db-data"


def test_remote_k8s_skips_a_relative_volume_path(tmp_path):
    # There the spec's path is bound on a node of the cluster, so a path relative to
    # a directory on this machine means nothing and no PV can be made from it.
    cluster_info = make_cluster_info(
        tmp_path,
        VOLUME_POD,
        {"stack": "teststack", "deploy-to": "k8s", "volumes": {"db-data": "./data/db-data"}},
    )

    assert cluster_info.get_pvs() == []


def test_remote_k8s_binds_an_absolute_volume_path(tmp_path):
    cluster_info = make_cluster_info(
        tmp_path,
        VOLUME_POD,
        {"stack": "teststack", "deploy-to": "k8s", "volumes": {"db-data": "/srv/db-data"}},
    )

    pvs = [k8s_dict(pv) for pv in cluster_info.get_pvs()]
    assert len(pvs) == 1
    assert pvs[0]["spec"]["hostPath"]["path"] == "/srv/db-data"
