# Copyright © 2023 Vulcanize
# Copyright © 2025 Bozeman Pass, Inc.

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

import click
import json

from importlib import resources, metadata

from stack.log import output_main


def _installed_commit_hash():
    # When installed from a git URL (e.g. uv tool install git+https://...),
    # PEP 610 direct_url.json in the dist-info records the source commit.
    try:
        direct_url_text = metadata.distribution("stack").read_text("direct_url.json")
        if direct_url_text:
            commit_id = json.loads(direct_url_text).get("vcs_info", {}).get("commit_id")
            if commit_id:
                return commit_id[:7]
    except Exception:
        pass
    return None


@click.command()
@click.pass_context
def command(ctx):
    """print tool version"""

    # See: https://stackoverflow.com/a/20885799/1701505
    from stack import data

    if resources.is_resource(data, "build_tag.txt"):
        with resources.open_text(data, "build_tag.txt") as version_file:
            # TODO: code better version that skips comment lines
            version_string = version_file.read().splitlines()[1]
    else:
        commit_hash = _installed_commit_hash()
        version_string = metadata.version("stack") + "-" + (commit_hash if commit_hash else "unknown")

    output_main(version_string)
