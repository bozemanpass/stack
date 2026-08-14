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

"""Ambient backup configuration, shared by both deployment targets.

Backup is configured once for an environment -- as profile settings or STACK_
environment variables -- and then applies to every deployment made under it, with
nothing backup-specific in the stack or the spec.  See docs/backup.md.

The two targets run different engines against the same restic repository format:
the Docker target runs restic in a mixed-in backup container, and Kubernetes hands
the same settings to K8up.  Both read them from here, so "what backup is
configured to do" has one definition rather than one per target.
"""

from dataclasses import dataclass

from stack.config.util import get_config_setting
from stack.log import log_warn

# A daily backup at 03:00, pruned weekly an hour later.  Both are ordinary cron
# expressions on both targets.
DEFAULT_SCHEDULE = "0 3 * * *"
DEFAULT_PRUNE_SCHEDULE = "0 4 * * 0"
DEFAULT_RETENTION = "--keep-daily 7 --keep-weekly 4 --keep-monthly 6"

# restic's retention flags, and the K8up Schedule retention fields they map onto.
_RETENTION_FLAGS = {
    "--keep-last": "keepLast",
    "--keep-hourly": "keepHourly",
    "--keep-daily": "keepDaily",
    "--keep-weekly": "keepWeekly",
    "--keep-monthly": "keepMonthly",
    "--keep-yearly": "keepYearly",
}


@dataclass
class BackupSettings:
    """What backup is configured to do, resolved from the environment/profile."""

    enabled: bool
    s3_endpoint: str
    s3_bucket: str
    s3_key_id: str
    s3_key: str
    restic_password: str
    schedule: str
    prune_schedule: str
    retention: str

    def missing_settings(self):
        """The names of the settings that are required but not set.

        The encryption key is included: restic cannot read back a repository
        without it, so a backup taken without one being deliberately chosen is
        worse than no backup at all (see the warning in docs/backup.md).
        """
        required = {
            "backup-s3-endpoint": self.s3_endpoint,
            "backup-s3-bucket": self.s3_bucket,
            "backup-s3-key-id": self.s3_key_id,
            "backup-s3-key": self.s3_key,
            "backup-restic-password": self.restic_password,
        }
        return [name for name, value in required.items() if not value]


def backup_settings() -> BackupSettings:
    return BackupSettings(
        enabled=bool(get_config_setting("backup", False)),
        s3_endpoint=get_config_setting("backup-s3-endpoint", ""),
        s3_bucket=get_config_setting("backup-s3-bucket", ""),
        s3_key_id=get_config_setting("backup-s3-key-id", ""),
        s3_key=get_config_setting("backup-s3-key", ""),
        restic_password=get_config_setting("backup-restic-password", ""),
        schedule=get_config_setting("backup-schedule", DEFAULT_SCHEDULE),
        prune_schedule=get_config_setting("backup-prune-schedule", DEFAULT_PRUNE_SCHEDULE),
        retention=get_config_setting("backup-retention", DEFAULT_RETENTION),
    )


def retention_policy(retention: str = DEFAULT_RETENTION):
    """Parse restic retention flags into K8up's structured retention fields.

    The setting is written as restic flags because that is what the Docker target
    passes straight to `restic forget`.  K8up wants the same policy as fields, so
    the one setting is translated here rather than asking for it twice in two
    notations.
    """
    policy = {}
    tokens = str(retention).split()
    i = 0
    while i < len(tokens):
        field = _RETENTION_FLAGS.get(tokens[i])
        if field and i + 1 < len(tokens) and tokens[i + 1].isdigit():
            policy[field] = int(tokens[i + 1])
            i += 2
            continue
        log_warn(f"WARN: ignoring unrecognized backup-retention token: {tokens[i]}")
        i += 1
    return policy
