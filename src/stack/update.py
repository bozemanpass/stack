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
import datetime
import filecmp
import os
from pathlib import Path
import requests
import sys
import stat
import shutil
import validators
from stack.util import get_yaml


DEFAULT_URL = "https://github.com/bozemanpass/stack/releases/latest/download/stack"


def _download_url(url: str, file_path: Path):
    r = requests.get(url, stream=True)
    r.raw.decode_content = True
    with open(file_path, "wb") as f:
        shutil.copyfileobj(r.raw, f)
    return r.status_code


def _error_exit(s: str):
    print(s)
    sys.exit(1)


# Note at present this probably won't work on non-Unix based OSes like Windows
@click.command()
@click.option("--check-only", is_flag=True, default=False, help="only check, don't update")
@click.pass_context
def command(ctx, check_only):
    """update shiv binary from a distribution url"""
    # Get the distribution URL from config
    config_key = "distribution-url"
    config_file_path = Path(os.path.expanduser("~/.stack/config.yml"))
    distribution_url = DEFAULT_URL

    if config_file_path.exists():
        yaml = get_yaml()
        config = yaml.load(open(config_file_path, "r"))
        if config_key in config:
            distribution_url = config[config_key]

    # Sanity check the URL
    if not validators.url(distribution_url):
        _error_exit(f"ERROR: distribution url: {distribution_url} is not valid")
    # Figure out the filename for ourselves
    shiv_binary_path = Path(sys.argv[0])
    timestamp_filename = f"stack-download-{datetime.datetime.now().strftime('%y%m%d-%H%M%S')}"
    temp_download_path = shiv_binary_path.parent.joinpath(timestamp_filename)
    # Download the file to a temp filename
    if ctx.obj.verbose:
        print(f"Downloading from: {distribution_url} to {temp_download_path}")
    status_code = _download_url(distribution_url, temp_download_path)
    if status_code != 200:
        os.unlink(temp_download_path)
        _error_exit(f"HTTP error {status_code} downloading from {distribution_url}")
    # Set the executable bit
    existing_mode = os.stat(temp_download_path)
    os.chmod(temp_download_path, existing_mode.st_mode | stat.S_IXUSR)
    # Switch the new file for the path we ran from
    # Check if the downloaded file is identical to the existing one
    same = filecmp.cmp(temp_download_path, shiv_binary_path)
    if same:
        if not ctx.obj.quiet or check_only:
            print("No update available, latest version already installed")
    else:
        if not ctx.obj.quiet:
            print("Update available")
        if check_only:
            if not ctx.obj.quiet:
                print("Check-only node, update not installed")
        else:
            if not ctx.obj.quiet:
                print("Installing...")
            if ctx.obj.verbose:
                print(f"Replacing: {shiv_binary_path} with {temp_download_path}")
            current_permissions = stat.S_IMODE(os.lstat(shiv_binary_path).st_mode)
            os.replace(temp_download_path, shiv_binary_path)
            os.chmod(shiv_binary_path, current_permissions)
            if not ctx.obj.quiet:
                print('Run "stack version" to see the newly installed version')
