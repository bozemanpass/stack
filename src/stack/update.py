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

from stack.config.util import get_config_setting
from stack.log import log_debug, log_info
from stack.util import error_exit


DEFAULT_URL = "https://github.com/bozemanpass/stack/releases/latest/download/stack"


def _download_url(url: str, file_path: Path):
    r = requests.get(url, stream=True)
    r.raw.decode_content = True
    with open(file_path, "wb") as f:
        shutil.copyfileobj(r.raw, f)
    return r.status_code


# Note at present this probably won't work on non-Unix based OSes like Windows
@click.command()
@click.option("--check-only", is_flag=True, default=False, help="only check, don't update")
@click.option(
    "--distribution-url", help="the distribution url to check", default=get_config_setting("distribution-url", default=DEFAULT_URL)
)
@click.pass_context
def command(ctx, check_only, distribution_url):
    """update shiv binary from a distribution url"""
    # Get the distribution URL from config
    # Sanity check the URL
    if not validators.url(distribution_url):
        error_exit(f"ERROR: distribution url: {distribution_url} is not valid")
    # Figure out the filename for ourselves
    shiv_binary_path = Path(sys.argv[0])

    if not os.access(shiv_binary_path, os.W_OK):
        error_exit(f"Cannot write to {shiv_binary_path}.  Try: sudo {shiv_binary_path} update")

    timestamp_filename = f"stack-download-{datetime.datetime.now().strftime("%y%m%d-%H%M%S")}"
    temp_download_path = shiv_binary_path.parent.joinpath(timestamp_filename)
    # Download the file to a temp filename
    log_debug(f"Downloading from: {distribution_url} to {temp_download_path}")
    status_code = _download_url(distribution_url, temp_download_path)
    if status_code != 200:
        os.unlink(temp_download_path)
        error_exit(f"HTTP error {status_code} downloading from {distribution_url}")
    # Set the executable bit
    existing_mode = os.stat(temp_download_path)
    os.chmod(temp_download_path, existing_mode.st_mode | stat.S_IXUSR)
    # Switch the new file for the path we ran from
    # Check if the downloaded file is identical to the existing one
    same = filecmp.cmp(temp_download_path, shiv_binary_path)
    if same:
        log_info("No update available, latest version already installed")
    else:
        log_debug("Update available")
        if check_only:
            log_info("Check-only node, update not installed")
        else:
            log_debug("Installing...")
            log_debug(f"Replacing: {shiv_binary_path} with {temp_download_path}")
            current_permissions = stat.S_IMODE(os.lstat(shiv_binary_path).st_mode)
            os.replace(temp_download_path, shiv_binary_path)
            os.chmod(shiv_binary_path, current_permissions)
            log_info('Run "stack version" to see the newly installed version')
