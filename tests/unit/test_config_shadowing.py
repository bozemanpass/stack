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

"""A deployment config value an inline `environment:` literal outranks.

The precedence itself is compose's and is not in question (docs/stack-files.md, and
tests/unit/test_k8s_objects.py for the k8s half of it).  What is under test here is
that `stack deploy` says so: a `--config` the deployer supplied that cannot reach the
container is the case where a stack comes up wrong rather than failing (issue #281).
"""

import textwrap

from conftest import make_stack_from_compose, run_stack


POD = """\
    services:
      probe:
        image: alpine:local
        environment:
          PUBLIC_BASE_URL: http://localhost
          QUIET: unrelated
        ports:
          - "8080"
      db:
        image: postgres:local
    """


def deploy(tmp_path, isolated_env, pod=POD, config=("PUBLIC_BASE_URL=https://example.com",)):
    stack_dir = make_stack_from_compose(tmp_path, textwrap.dedent(pod))
    spec_file = tmp_path / "spec.yml"
    args = ["init", "--stack", str(stack_dir), "--output", str(spec_file)]
    for entry in config:
        args += ["--config", entry]
    result = run_stack(args, isolated_env, cwd=tmp_path)
    assert result.returncode == 0, f"init failed:\n{result.stdout}\n{result.stderr}"
    result = run_stack(
        ["deploy", "--spec-file", str(spec_file), "--deployment-dir", str(tmp_path / "deployment")],
        isolated_env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, f"deploy failed:\n{result.stdout}\n{result.stderr}"
    return result


def test_a_shadowed_config_value_is_reported(tmp_path, isolated_env):
    result = deploy(tmp_path, isolated_env)
    # Named service and key, both values, and the way out.
    assert "probe" in result.stderr
    assert "PUBLIC_BASE_URL" in result.stderr
    assert "http://localhost" in result.stderr
    assert "https://example.com" in result.stderr
    assert 'PUBLIC_BASE_URL: "${PUBLIC_BASE_URL}"' in result.stderr
    # The deployment is still created: this is the documented behaviour, not an error.
    assert "PUBLIC_BASE_URL=https://example.com" in (tmp_path / "deployment" / "config.env").read_text()


def test_keys_that_are_not_shadowed_are_not_reported(tmp_path, isolated_env):
    # `db` declares nothing inline, and `QUIET` is not a config value at all.
    result = deploy(tmp_path, isolated_env)
    assert "db:" not in result.stderr
    assert "QUIET" not in result.stderr


def test_a_forwarded_value_is_not_reported(tmp_path, isolated_env):
    # The documented fix, which must not itself look like the problem.
    pod = """\
        services:
          probe:
            image: alpine:local
            environment:
              PUBLIC_BASE_URL: ${PUBLIC_BASE_URL}
            ports:
              - "8080"
        """
    result = deploy(tmp_path, isolated_env, pod=pod)
    assert "PUBLIC_BASE_URL" not in result.stderr


def test_a_sequence_entry_with_no_value_is_not_reported(tmp_path, isolated_env):
    # `- PUBLIC_BASE_URL` carries no value of its own, so it shadows nothing.
    pod = """\
        services:
          probe:
            image: alpine:local
            environment:
              - PUBLIC_BASE_URL
            ports:
              - "8080"
        """
    result = deploy(tmp_path, isolated_env, pod=pod)
    assert "PUBLIC_BASE_URL" not in result.stderr


def test_an_inline_literal_matching_the_config_is_not_reported(tmp_path, isolated_env):
    # Same value from both sources: the container sees what the deployer asked for.
    pod = """\
        services:
          probe:
            image: alpine:local
            environment:
              - PUBLIC_BASE_URL=https://example.com
            ports:
              - "8080"
        """
    result = deploy(tmp_path, isolated_env, pod=pod)
    assert "PUBLIC_BASE_URL" not in result.stderr
