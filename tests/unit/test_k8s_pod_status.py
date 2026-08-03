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

"""Tests for the pod status summary reported by "stack manage status"."""

from types import SimpleNamespace

import pytest

from stack.deploy.k8s.deploy_k8s import _pod_status


def pod(phase, readies=None):
    """Stands in for a V1Pod; _pod_status only reads phase and container_statuses."""
    container_statuses = None if readies is None else [SimpleNamespace(ready=r) for r in readies]
    return SimpleNamespace(status=SimpleNamespace(phase=phase, container_statuses=container_statuses))


@pytest.mark.parametrize(
    "phase,readies,expected",
    [
        ("Pending", None, "Pending"),
        ("Failed", [False], "Failed"),
        ("Succeeded", None, "Succeeded"),
        # Running but not yet ready must not report as Running: the containers
        # have started, but the application inside them cannot serve yet.
        ("Running", None, "Starting 0/0 ready"),
        ("Running", [False], "Starting 0/1 ready"),
        ("Running", [True, False], "Starting 1/2 ready"),
        ("Running", [True], "Running 1/1 ready"),
        ("Running", [True, True], "Running 2/2 ready"),
    ],
)
def test_pod_status(phase, readies, expected):
    assert _pod_status(pod(phase, readies)) == expected


@pytest.mark.parametrize(
    "phase,readies",
    [
        ("Pending", None),
        ("Running", None),
        ("Running", [False]),
        ("Running", [True, False]),
    ],
)
def test_not_ready_never_says_running(phase, readies):
    # The deploy tests count ready pods with a case-insensitive grep for
    # "running", so no unready pod may contain that word.
    assert "running" not in _pod_status(pod(phase, readies)).lower()
