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

"""Tests for what the Stack model reads out of a stack's composefiles.

The `@stack` annotations are parsed out of YAML *comments*, which ruamel attaches to
whichever node it thinks they belong to.  That attachment is subtle -- a comment heading
the next block lands on the previous item -- so these behaviors are worth pinning
directly rather than inferring from whether a deployment came out right.
"""

import pytest

from conftest import make_stack_from_compose
from stack.deploy.stack import Stack


def load_stack(tmp_path, compose_yaml, name="teststack"):
    """A Stack whose single pod is the given (dedented) composefile.

    The stack must sit in a git checkout: pod file resolution goes through the stack's
    repo path, and a stack.yml outside a repo has no derivable repo reference.
    """
    stack_dir = make_stack_from_compose(tmp_path, compose_yaml, name=name)
    return Stack(name).init_from_file(stack_dir / "stack.yml")


# ---------------------------------------------------------------------------
# get_ports
# ---------------------------------------------------------------------------


def test_ports_normalized_to_strings(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          web:
            image: nginx:local
            ports:
              - 80
              - "8080:81"
              - "53/udp"
        """,
    )
    # A YAML scalar port is an int; downstream code assumes strings throughout.
    assert stack.get_ports() == {"web": ["80", "8080:81", "53/udp"]}


def test_ports_absent_for_service_without_ports(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          worker:
            image: worker:local
        """,
    )
    assert stack.get_ports() == {}


# ---------------------------------------------------------------------------
# get_http_proxy_targets
# ---------------------------------------------------------------------------


def test_http_proxy_target_from_annotation(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          web:
            image: nginx:local
            ports:
              - "80"  # @stack http-proxy /
        """,
    )
    assert stack.get_http_proxy_targets() == [{"service": "web", "port": "80", "path": "/"}]


def test_no_http_proxy_target_without_annotation(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          web:
            image: nginx:local
            ports:
              - "80"
        """,
    )
    assert stack.get_http_proxy_targets() == []


def test_http_proxy_annotation_with_subpath(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          web:
            image: nginx:local
            ports:
              - "80"  # @stack http-proxy /api
        """,
    )
    assert stack.get_http_proxy_targets() == [{"service": "web", "port": "80", "path": "/api"}]


def test_http_proxy_annotation_path_normalized(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          web:
            image: nginx:local
            ports:
              - "80"  # @stack http-proxy api/v1/
        """,
    )
    # Leading and trailing slashes are normalized to a single leading one.
    assert stack.get_http_proxy_targets() == [{"service": "web", "port": "80", "path": "/api/v1"}]


def test_http_proxy_annotation_without_path_defaults_to_root(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          web:
            image: nginx:local
            ports:
              - "80"  # @stack http-proxy
        """,
    )
    assert stack.get_http_proxy_targets() == [{"service": "web", "port": "80", "path": "/"}]


def test_http_proxy_target_uses_container_port_of_mapped_port(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          web:
            image: nginx:local
            ports:
              - "8080:80"  # @stack http-proxy /
        """,
    )
    # The proxy connects to the ClusterIP service, so the container port is what counts.
    assert stack.get_http_proxy_targets() == [{"service": "web", "port": "80", "path": "/"}]


@pytest.mark.parametrize(
    "prefix, expected_path",
    [
        (None, "/api"),
        ("/", "/api"),
        ("/base", "/base/api"),
        # A prefix is normalized the same way a path is.
        ("base", "/base/api"),
        ("/base/", "/base/api"),
    ],
)
def test_http_proxy_prefix_applied(tmp_path, prefix, expected_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          web:
            image: nginx:local
            ports:
              - "80"  # @stack http-proxy /api
        """,
    )
    targets = stack.get_http_proxy_targets(prefix=prefix)
    assert targets == [{"service": "web", "port": "80", "path": expected_path}]


def test_http_proxy_annotation_only_on_annotated_port(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          web:
            image: nginx:local
            ports:
              - "80"  # @stack http-proxy /
              - "9090"
              - "9091"  # @stack http-proxy /metrics
        """,
    )
    assert stack.get_http_proxy_targets() == [
        {"service": "web", "port": "80", "path": "/"},
        {"service": "web", "port": "9091", "path": "/metrics"},
    ]


def test_unrelated_comment_on_port_ignored(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          web:
            image: nginx:local
            ports:
              - "80"  # the main listener
        """,
    )
    assert stack.get_http_proxy_targets() == []


# ---------------------------------------------------------------------------
# get_backup_targets
# ---------------------------------------------------------------------------


def test_backup_exclude_annotation(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          web:
            image: nginx:local
            volumes:
              - web-data:/data
              - web-cache:/cache  # @stack backup-exclude
        volumes:
          web-data:
          web-cache:
        """,
    )
    assert stack.get_backup_targets() == {"exclude": ["web-cache"], "commands": {}}


def test_no_backup_exclude_without_annotation(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          web:
            image: nginx:local
            volumes:
              - web-data:/data
        volumes:
          web-data:
        """,
    )
    assert stack.get_backup_targets() == {"exclude": [], "commands": {}}


def test_backup_exclude_ignores_trailing_block_comment(tmp_path):
    # ruamel attaches a comment that heads the *next* block to the last item of the
    # previous one.  Only an end-of-line comment may count as an annotation, or a
    # comment about a later service would silently exclude an earlier volume.
    stack = load_stack(
        tmp_path,
        """\
        services:
          web:
            image: nginx:local
            volumes:
              - web-data:/data
          # @stack backup-exclude applies to nothing here
          other:
            image: other:local
        volumes:
          web-data:
        """,
    )
    assert stack.get_backup_targets() == {"exclude": [], "commands": {}}


# ---------------------------------------------------------------------------
# get_named_volumes
# ---------------------------------------------------------------------------


def test_named_volumes_split_by_access_mode(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          web:
            image: nginx:local
            volumes:
              - rw-data:/rw
              - ro-config:/ro:ro
        volumes:
          rw-data:
          ro-config:
        """,
    )
    assert stack.get_named_volumes() == {"rw": ["rw-data"], "ro": ["ro-config"]}


def test_named_volume_used_read_write_and_read_only_is_rw_only(tmp_path):
    """A volume mounted rw by one service and ro by another belongs in "rw" alone."""
    stack = load_stack(
        tmp_path,
        """\
        services:
          writer:
            image: nginx:local
            volumes:
              - shared:/rw
          reader:
            image: nginx:local
            volumes:
              - shared:/ro:ro
        volumes:
          shared:
        """,
    )
    # One writer means the volume must be provisioned writable.
    assert stack.get_named_volumes() == {"rw": ["shared"], "ro": []}


@pytest.mark.xfail(
    strict=True,
    reason="Classification depends on the order services appear in the composefile.  "
    "get_named_volumes() makes the 'rw' list sticky (the ro branch skips a volume "
    "already in rw) but not the other way round, so a volume seen ro-first lands in "
    "both lists.  init_operation() then iterates both, and for k8s a volume whose name "
    "contains 'config' is emitted as a configmap as well as a volume -- which would "
    "mount it read-only and break the writer.",
)
def test_named_volume_read_only_use_seen_first_still_classified_rw(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          reader:
            image: nginx:local
            volumes:
              - shared:/ro:ro
          writer:
            image: nginx:local
            volumes:
              - shared:/rw
        volumes:
          shared:
        """,
    )
    assert stack.get_named_volumes() == {"rw": ["shared"], "ro": []}


def test_declared_but_unused_volume_is_not_reported(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          web:
            image: nginx:local
        volumes:
          orphan:
        """,
    )
    assert stack.get_named_volumes() == {"rw": [], "ro": []}


# ---------------------------------------------------------------------------
# get_security_settings
# ---------------------------------------------------------------------------


def test_security_settings_read_privileged(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          web:
            image: nginx:local
            privileged: true
          worker:
            image: worker:local
        """,
    )
    assert stack.get_security_settings() == {"web": {"privileged": True}}


# ---------------------------------------------------------------------------
# pod list formats
# ---------------------------------------------------------------------------


def test_pod_list_new_format(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          web:
            image: nginx:local
        """,
    )
    assert stack.get_pod_list() == ["web"]


def test_pod_list_legacy_string_format(tmp_path):
    stack_file = tmp_path / "stack.yml"
    stack_file.write_text("name: teststack\npods:\n  - web\n")
    stack = Stack("teststack").init_from_file(stack_file)
    assert stack.get_pod_list() == ["web"]


def test_pod_list_empty(tmp_path):
    stack_file = tmp_path / "stack.yml"
    stack_file.write_text("name: teststack\n")
    stack = Stack("teststack").init_from_file(stack_file)
    assert stack.get_pod_list() == []
