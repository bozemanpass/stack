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

"""K8up resources for backing up a deployment's persistent data.

On Kubernetes the backup engine is [K8up](https://k8up.io), a restic-based backup
operator.  stack does not install it and does not run restic itself: it emits the
resources that reference K8up -- a Schedule for the deployment's namespace, and
Backup/Restore objects for operations asked for by hand -- exactly as it emits
Certificates and leaves the issuing to cert-manager.  A cluster without K8up
fails the same recognisable way a cluster without cert-manager does.

K8up backs up every PVC in the namespace, mounting each at /data/<claim-name> in
the backup job, so what gets backed up follows from the deployment itself with no
list to maintain.  A volume the stack author marked `@stack backup-exclude` is
annotated k8up.io/backup=false on its PVC, which is K8up's own opt-out (see
cluster_info.get_pvcs).

Each deployment gets its own restic repository, named for the deployment inside
the configured bucket (see backend_spec), on both targets.
"""

from datetime import datetime, timezone
from time import sleep

from kubernetes import client

from stack.deploy.backup import BackupSettings, retention_policy
from stack.deploy.deployer import DeployerException
from stack.log import log_debug, log_info

K8UP_GROUP = "k8up.io"
K8UP_VERSION = "v1"

SCHEDULES = "schedules"
BACKUPS = "backups"
RESTORES = "restores"
SNAPSHOTS = "snapshots"

# One Schedule and one Secret per deployment namespace.
SCHEDULE_NAME = "stack-backup"
SECRET_NAME = "stack-backup"

# Keys within that Secret.  K8up reads each through its own SecretKeySelector, so
# the names are ours to choose.
RESTIC_PASSWORD_KEY = "restic-password"
S3_KEY_ID_KEY = "s3-key-id"
S3_KEY_KEY = "s3-key"

# K8up's opt-out annotation, applied to a PVC the stack author excluded.
BACKUP_ANNOTATION = "k8up.io/backup"

# K8up's consistency-dump annotations, applied to the pod of a service the stack
# author gave a `@stack backup-command`: K8up execs the command in the pod at
# backup time and stores its stdout as a snapshot of its own, named with the
# given file extension.
BACKUP_COMMAND_ANNOTATION = "k8up.io/backupcommand"
FILE_EXTENSION_ANNOTATION = "k8up.io/file-extension"

# How long to wait for an on-demand Backup or Restore to finish.  Both run as
# ordinary Jobs whose pod has to be scheduled and pull an image first, so the
# floor is not small; the ceiling only has to be larger than a real transfer.
_JOB_POLL_SECONDS = 5
_JOB_TIMEOUT_SECONDS = 1800


class K8upException(DeployerException):
    """A backup or restore K8up ran did not succeed.

    A DeployerException so that it reports the same way a failed operation on the
    other target does, rather than as a traceback.
    """


def k8up_available(custom_obj_api: client.CustomObjectsApi) -> bool:
    """True if this cluster has K8up's API registered.

    The check is for the CRD being served rather than for the operator pod: a
    cluster with the CRDs but no operator accepts the resources and never acts on
    them, which is indistinguishable from here and is a cluster-provisioning
    fault, not a deployment-time one.
    """
    try:
        custom_obj_api.list_cluster_custom_object(
            group=K8UP_GROUP,
            version=K8UP_VERSION,
            plural=SCHEDULES,
        )
        return True
    except client.exceptions.ApiException as e:
        log_debug(f"K8up not available ({e.status})")
        return False


def backup_secret(namespace: str, settings: BackupSettings) -> client.V1Secret:
    """The Secret holding the repository password and object store credentials.

    K8up's jobs read these from the namespace they run in, so each deployment
    carries its own copy rather than sharing one from elsewhere in the cluster.
    """
    return client.V1Secret(
        metadata=client.V1ObjectMeta(name=SECRET_NAME, namespace=namespace),
        string_data={
            RESTIC_PASSWORD_KEY: settings.restic_password,
            S3_KEY_ID_KEY: settings.s3_key_id,
            S3_KEY_KEY: settings.s3_key,
        },
    )


def repository_bucket(settings: BackupSettings, name: str) -> str:
    """The bucket path of the repository belonging to the deployment `name`.

    K8up builds the restic repository as "s3:<endpoint>/<bucket>", so naming the
    deployment inside the bucket puts each deployment in a repository of its own.
    That is not just tidiness: K8up restores the latest snapshot matching a
    restore with no filter for which host wrote it, so deployments sharing one
    repository could restore each other's data.  It also matches what the Docker
    target does with the same setting.

    A deployment's own name is what it backs up to.  A restore can name another
    deployment's instead (see run_restore), which is how a new deployment is
    seeded from an existing backup without either of them borrowing the other's
    identity.
    """
    return f"{settings.s3_bucket.rstrip('/')}/{name}"


def backend_spec(settings: BackupSettings, namespace: str):
    """The `backend` block shared by Schedule, Backup and Restore."""
    return {
        "repoPasswordSecretRef": {"name": SECRET_NAME, "key": RESTIC_PASSWORD_KEY},
        "s3": {
            "endpoint": settings.s3_endpoint,
            "bucket": repository_bucket(settings, namespace),
            "accessKeyIDSecretRef": {"name": SECRET_NAME, "key": S3_KEY_ID_KEY},
            "secretAccessKeySecretRef": {"name": SECRET_NAME, "key": S3_KEY_KEY},
        },
    }


def schedule_object(namespace: str, settings: BackupSettings):
    return {
        "apiVersion": f"{K8UP_GROUP}/{K8UP_VERSION}",
        "kind": "Schedule",
        "metadata": {"name": SCHEDULE_NAME, "namespace": namespace},
        "spec": {
            "backend": backend_spec(settings, namespace),
            "backup": {"schedule": settings.schedule},
            # Retention is applied by prune, so a repository configured with a
            # retention policy but no prune schedule would grow forever.
            "prune": {
                "schedule": settings.prune_schedule,
                "retention": retention_policy(settings.retention),
            },
        },
    }


def _create(custom_obj_api: client.CustomObjectsApi, namespace: str, plural: str, body):
    log_debug(f"Creating {plural}: {body}")
    return custom_obj_api.create_namespaced_custom_object(
        group=K8UP_GROUP,
        version=K8UP_VERSION,
        namespace=namespace,
        plural=plural,
        body=body,
    )


def _delete(custom_obj_api: client.CustomObjectsApi, namespace: str, plural: str, name: str):
    try:
        custom_obj_api.delete_namespaced_custom_object(
            group=K8UP_GROUP,
            version=K8UP_VERSION,
            namespace=namespace,
            plural=plural,
            name=name,
        )
    except client.exceptions.ApiException as e:
        if e.status != 404:
            raise
        log_debug(f"No {plural}/{name} to delete")


def ensure_backup_configured(
    core_api: client.CoreV1Api,
    custom_obj_api: client.CustomObjectsApi,
    namespace: str,
    settings: BackupSettings,
):
    """Create (or update) this deployment's backup Secret and Schedule."""
    secret = backup_secret(namespace, settings)
    try:
        core_api.create_namespaced_secret(namespace=namespace, body=secret)
    except client.exceptions.ApiException as e:
        if e.status != 409:
            raise
        # A redeploy over an existing namespace: the settings may have changed.
        core_api.replace_namespaced_secret(name=SECRET_NAME, namespace=namespace, body=secret)

    schedule = schedule_object(namespace, settings)
    try:
        _create(custom_obj_api, namespace, SCHEDULES, schedule)
    except client.exceptions.ApiException as e:
        if e.status != 409:
            raise
        custom_obj_api.patch_namespaced_custom_object(
            group=K8UP_GROUP,
            version=K8UP_VERSION,
            namespace=namespace,
            plural=SCHEDULES,
            name=SCHEDULE_NAME,
            body={"spec": schedule["spec"]},
        )
    log_info(f"Backup scheduled: '{settings.schedule}' to {settings.s3_endpoint}/{settings.s3_bucket}/{namespace}")


def delete_backup_configuration(
    core_api: client.CoreV1Api,
    custom_obj_api: client.CustomObjectsApi,
    namespace: str,
):
    """Remove the Schedule and Secret, leaving the repository itself alone.

    Stopping a deployment must not destroy its backups: the whole point of them
    is to outlive the deployment.  Only the scheduling stops.
    """
    _delete(custom_obj_api, namespace, SCHEDULES, SCHEDULE_NAME)
    try:
        core_api.delete_namespaced_secret(name=SECRET_NAME, namespace=namespace)
    except client.exceptions.ApiException as e:
        if e.status != 404:
            raise


def _completion_condition(status):
    for condition in status.get("conditions", []):
        if condition.get("type") == "Completed":
            return condition
    return None


def _wait_for_completion(custom_obj_api: client.CustomObjectsApi, namespace: str, plural: str, name: str):
    """Block until a Backup/Restore finishes, raising if it failed."""
    waited = 0
    while waited < _JOB_TIMEOUT_SECONDS:
        obj = custom_obj_api.get_namespaced_custom_object(
            group=K8UP_GROUP,
            version=K8UP_VERSION,
            namespace=namespace,
            plural=plural,
            name=name,
        )
        status = obj.get("status", {})
        condition = _completion_condition(status)
        if condition and condition.get("status") == "True":
            # K8up reports both success and failure by completing the job; the
            # reason is what separates them.
            if condition.get("reason") == "Succeeded":
                return obj
            raise K8upException(f"{plural}/{name} failed: {condition.get('message', condition.get('reason'))}")
        sleep(_JOB_POLL_SECONDS)
        waited += _JOB_POLL_SECONDS
    raise K8upException(f"timed out after {_JOB_TIMEOUT_SECONDS}s waiting for {plural}/{name}")


def _unique_name(prefix: str) -> str:
    # K8up keeps finished jobs around, so each on-demand object needs a name of
    # its own.  Seconds are enough to separate operations a person triggers.
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"


def run_backup(custom_obj_api: client.CustomObjectsApi, namespace: str, settings: BackupSettings):
    """Take a backup now, outside the schedule, and wait for it to finish."""
    name = _unique_name("stack-backup")
    body = {
        "apiVersion": f"{K8UP_GROUP}/{K8UP_VERSION}",
        "kind": "Backup",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {"backend": backend_spec(settings, namespace)},
    }
    _create(custom_obj_api, namespace, BACKUPS, body)
    log_info(f"Backup {name} started")
    _wait_for_completion(custom_obj_api, namespace, BACKUPS, name)
    log_info(f"Backup {name} complete")


def run_restore(
    custom_obj_api: client.CustomObjectsApi,
    namespace: str,
    settings: BackupSettings,
    volume: str,
    snapshot: str = None,
    source: str = None,
):
    """Restore one volume in place, and wait for it to finish.

    K8up restores into a single claim at a time, so a deployment-wide restore is
    one of these per volume.

    Which snapshot is left to K8up: `paths` narrows its snapshot list to the one
    volume being restored (K8up backs each volume up as a snapshot of its own,
    under /data/<claim>), and it then takes the most recent of those.  Resolving
    that here instead would mean reading the repository, which for a restore from
    somewhere else this deployment cannot do.  K8up trims the /data/<claim> prefix
    as it writes, so the files land at the root of the claim they came from.

    `source` names another deployment to restore *from*.  It changes the backend
    this one Restore reads and nothing else: the deployment keeps its own identity
    and goes on backing up to its own repository, which is what makes it possible
    to seed several new deployments from one existing backup.
    """
    name = _unique_name(f"stack-restore-{volume}")
    spec = {
        "backend": backend_spec(settings, source or namespace),
        "restoreMethod": {"folder": {"claimName": volume}},
        "paths": [f"/data/{volume}"],
    }
    if snapshot and snapshot != "latest":
        spec["snapshot"] = snapshot
    body = {
        "apiVersion": f"{K8UP_GROUP}/{K8UP_VERSION}",
        "kind": "Restore",
        "metadata": {"name": name, "namespace": namespace},
        "spec": spec,
    }
    _create(custom_obj_api, namespace, RESTORES, body)
    log_info(f"Restore of {volume} started ({name})")
    _wait_for_completion(custom_obj_api, namespace, RESTORES, name)
    log_info(f"Restore of {volume} complete")


def list_snapshots(custom_obj_api: client.CustomObjectsApi, namespace: str):
    """The snapshots K8up has synced into this namespace, oldest first.

    K8up's backup job writes a Snapshot object per snapshot in the repository
    when it finishes, so this reads the repository's contents without needing
    restic or the object store's credentials here.
    """
    response = custom_obj_api.list_namespaced_custom_object(
        group=K8UP_GROUP,
        version=K8UP_VERSION,
        namespace=namespace,
        plural=SNAPSHOTS,
    )
    snapshots = []
    for item in response.get("items", []):
        spec = item.get("spec", {})
        snapshots.append(
            {
                "id": spec.get("id", ""),
                "date": spec.get("date", ""),
                "volumes": volumes_in_paths(spec.get("paths", [])),
            }
        )
    snapshots.sort(key=lambda s: s["date"])
    return snapshots


def volumes_in_paths(paths):
    """The volume names behind a snapshot's paths (/data/<claim-name>)."""
    volumes = []
    for path in paths:
        name = path.strip("/").split("/")[-1]
        if name and name not in volumes:
            volumes.append(name)
    return volumes
