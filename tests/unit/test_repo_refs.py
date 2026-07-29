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

"""Tests for parsing repository references.

A repo reference determines where a repo is cloned to on disk, which container registry
its images belong in, and -- through the recipe repo -- what an image is tagged with.
Mis-parsing one sends work to the wrong place rather than failing outright.
"""

from pathlib import Path

import pytest

from stack.repos.repo_util import (
    branch_strip,
    fs_path_for_repo,
    host_and_path_for_repo,
    image_registry_for_repo,
    parse_branches,
)
from stack.util import include_exclude_check


@pytest.mark.parametrize(
    "ref, expected",
    [
        # An unqualified two-part ref means github, for backwards compatibility.
        ("org/repo", ("github.com", "org/repo", None)),
        ("example.com/org/repo", ("example.com", "org/repo", None)),
        # A branch or tag may be appended with '@'.
        ("org/repo@main", ("github.com", "org/repo", "main")),
        ("example.com/org/repo@v1.2.3", ("example.com", "org/repo", "v1.2.3")),
        ("org/repo@" + "a" * 40, ("github.com", "org/repo", "a" * 40)),
        # Neither a bare name nor a too-deep path names a repo.
        ("repo", (None, None, None)),
        ("example.com/org/group/repo", (None, None, None)),
    ],
)
def test_host_and_path_for_repo(ref, expected):
    assert host_and_path_for_repo(ref) == expected


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("org/repo", "ghcr.io"),
        ("github.com/org/repo", "ghcr.io"),
        ("gitlab.com/org/repo", "registry.gitlab.com"),
        ("bitbucket.org/org/repo", "crg.apkg.io"),
        # A host with no known registry serves its own, so it maps to itself.  This is
        # the self-hosted Gitea/Forgejo case.
        ("git.example.com/org/repo", "git.example.com"),
        # A branch suffix must not change the registry.
        ("org/repo@main", "ghcr.io"),
        ("unparseable", None),
    ],
)
def test_image_registry_for_repo(ref, expected):
    assert image_registry_for_repo(ref) == expected


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("org/repo", "org/repo"),
        ("org/repo@main", "org/repo"),
        ("example.com/org/repo@v1", "example.com/org/repo"),
    ],
)
def test_branch_strip(ref, expected):
    assert branch_strip(ref) == expected


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("org/repo", "github.com/org/repo"),
        ("example.com/org/repo", "example.com/org/repo"),
        # The branch is not part of the checkout path: one clone per repo.
        ("org/repo@main", "github.com/org/repo"),
    ],
)
def test_fs_path_for_repo(ref, expected, tmp_path):
    assert fs_path_for_repo(ref, tmp_path) == Path(tmp_path).joinpath(expected)


def test_fs_path_for_unparseable_repo():
    assert fs_path_for_repo("unparseable", "/dev-root") is None


def test_parse_branches_none():
    assert parse_branches(None) is None
    assert parse_branches("") is None


def test_parse_branches_normalizes_to_space_separated_pairs():
    assert parse_branches("org/a@main,org/b@v1") == ["org/a main", "org/b v1"]


def test_parse_branches_rejects_missing_branch():
    # A directive with no '@' is a user error and must not be silently ignored.
    with pytest.raises(SystemExit):
        parse_branches("org/a")


@pytest.mark.parametrize(
    "value, include, exclude, expected",
    [
        ("a", None, None, True),
        ("a", "a,b", None, True),
        ("c", "a,b", None, False),
        ("a", None, "a,b", False),
        ("c", None, "a,b", True),
        # include wins when both are given.
        ("a", "a", "a", True),
    ],
)
def test_include_exclude_check(value, include, exclude, expected):
    assert include_exclude_check(value, include, exclude) is expected
