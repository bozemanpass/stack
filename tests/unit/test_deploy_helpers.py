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

"""Tests for the helpers that turn CLI arguments and a stack into a deployment spec."""

import re

import pytest

from stack.deploy.deploy_util import convert_to_seconds
from stack.deploy.deployment_create import _get_mapped_ports, _parse_config_variables
from stack.init.init import _parse_http_proxy


class StackWithPorts:
    """Stands in for a Stack; _get_mapped_ports only reads get_ports()."""

    def __init__(self, ports):
        self._ports = ports

    def get_ports(self):
        # A fresh copy per call, as Stack.get_ports() builds one from the pod files.
        return {svc: list(ports) for svc, ports in self._ports.items()}


# ---------------------------------------------------------------------------
# convert_to_seconds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (30, 30),
        ("30", 30),
        ("45s", 45),
        ("2m", 120),
        ("1h", 3600),
        ("90s", 90),
        ("0s", 0),
        # Days and weeks are accumulated separately from the seconds component.
        ("1d", 86400),
        ("2d", 172800),
        ("1w", 604800),
    ],
)
def test_convert_to_seconds(value, expected):
    assert convert_to_seconds(value) == expected


@pytest.mark.parametrize("value", ["30x", "abc", "m"])
def test_convert_to_seconds_rejects_unknown_units(value):
    with pytest.raises((KeyError, ValueError)):
        convert_to_seconds(value)


# ---------------------------------------------------------------------------
# _get_mapped_ports
# ---------------------------------------------------------------------------


def test_mapped_ports_no_ports():
    assert _get_mapped_ports(StackWithPorts({}), "any-same") == {}


def test_mapped_ports_no_recipe_leaves_ports_alone():
    stack = StackWithPorts({"web": ["8080:80"]})
    assert _get_mapped_ports(stack, None) == {"web": ["8080:80"]}


@pytest.mark.parametrize("recipe", ["any-variable-random", "k8s-clusterip-same"])
def test_mapped_ports_strips_host_mapping(recipe):
    stack = StackWithPorts({"web": ["80", "8080:81", "127.0.0.1:8443:82"]})
    # These recipes publish no host port, so only the container port survives.
    assert _get_mapped_ports(stack, recipe) == {"web": ["80", "81", "82"]}


def test_mapped_ports_localhost_same():
    stack = StackWithPorts({"web": ["80", "8080:81"]})
    assert _get_mapped_ports(stack, "localhost-same") == {
        "web": ["127.0.0.1:80:80", "127.0.0.1:81:81"]
    }


def test_mapped_ports_any_same():
    stack = StackWithPorts({"web": ["80"]})
    assert _get_mapped_ports(stack, "any-same") == {"web": ["0.0.0.0:80:80"]}


def test_mapped_ports_udp_kept_on_container_port_only():
    stack = StackWithPorts({"dns": ["53/udp"]})
    # The host side of the mapping must not carry the protocol suffix, but the
    # container side must keep it or the protocol is lost.
    assert _get_mapped_ports(stack, "any-same") == {"dns": ["0.0.0.0:53:53/udp"]}


@pytest.mark.parametrize(
    "recipe, host",
    [("localhost-fixed-random", "127.0.0.1"), ("any-fixed-random", "0.0.0.0")],
)
def test_mapped_ports_fixed_random_in_nodeport_range(recipe, host):
    stack = StackWithPorts({"web": ["80"]})
    mapped = _get_mapped_ports(stack, recipe)["web"][0]

    match = re.fullmatch(rf"{re.escape(host)}:(\d+):80", mapped)
    assert match, mapped
    # Constrained to the k8s NodePort range.
    assert 30000 <= int(match.group(1)) <= 32767


def test_mapped_ports_rejects_unknown_recipe():
    stack = StackWithPorts({"web": ["80"]})
    with pytest.raises(SystemExit):
        _get_mapped_ports(stack, "no-such-recipe")


# ---------------------------------------------------------------------------
# _parse_config_variables
# ---------------------------------------------------------------------------


def test_parse_config_variables_none():
    assert _parse_config_variables(None) is None
    assert _parse_config_variables("") is None


def test_parse_config_variables_pairs():
    assert _parse_config_variables("A=1,B=2") == {"A": "1", "B": "2"}


def test_parse_config_variables_rejects_bare_name():
    with pytest.raises(SystemExit):
        _parse_config_variables("A")


def test_parse_config_variables_rejects_extra_separator():
    # A value containing '=' cannot be expressed, and is rejected rather than truncated.
    with pytest.raises(SystemExit):
        _parse_config_variables("A=1=2")


# ---------------------------------------------------------------------------
# _parse_http_proxy
# ---------------------------------------------------------------------------


def test_parse_http_proxy_service_and_port():
    assert _parse_http_proxy("web:80") == {"service": "web", "port": "80", "path": "/"}


@pytest.mark.parametrize("value", ["http://web:80", "https://web:80"])
def test_parse_http_proxy_scheme_stripped(value):
    assert _parse_http_proxy(value) == {"service": "web", "port": "80", "path": "/"}


def test_parse_http_proxy_path_first():
    assert _parse_http_proxy("/api:web:80") == {"service": "web", "port": "80", "path": "/api"}


@pytest.mark.parametrize("value", ["web", "a:b:c:d"])
def test_parse_http_proxy_rejects_wrong_arity(value):
    with pytest.raises(SystemExit):
        _parse_http_proxy(value)


@pytest.mark.parametrize("value", ["web:80:/api", "/api:web:http"])
def test_parse_http_proxy_rejects_non_numeric_port(value):
    # The path leads: the reversed 'svc:port:path' form must fail rather than reach the spec.
    with pytest.raises(SystemExit):
        _parse_http_proxy(value)
