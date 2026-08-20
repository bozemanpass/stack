# Copyright © 2022, 2023 Vulcanize
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

import os

from pathlib import Path
from python_on_whales import DockerClient, DockerException

from stack import constants
from stack.deploy import secrets as stack_secrets
from stack.deploy.backup import backup_settings
from stack.deploy.deployer import Deployer, DeployerException, DeployerConfigGenerator
from stack.deploy.deployment_context import DeploymentContext
from stack.log import output_main, log_info
from stack.opts import opts
from stack.util import get_yaml, error_exit


def _local_image_id(tag):
    """The image ID a local tag resolves to, or None if the tag doesn't exist locally."""
    try:
        return DockerClient().image.inspect(tag).id
    except Exception:
        return None


class DockerDeployer(Deployer):
    name: str = "compose"
    type: str

    def __init__(
        self,
        type,
        deployment_context: DeploymentContext,
        compose_files,
        compose_project_name,
        compose_env_file,
    ) -> None:
        self.docker = DockerClient(
            compose_files=compose_files,
            compose_project_name=compose_project_name,
            compose_env_file=compose_env_file,
        )
        self.type = type
        self.compose_files = compose_files
        self.compose_project_name = compose_project_name
        self.deployment_context = deployment_context

    def _stage_local_images(self):
        """Point this deployment's private image tags at the current locally built images.

        `deploy` rewrites `<name>:stack` to `<name>:<cluster-id>` so that concurrent
        deployments on one host don't share a mutable tag, so the tag has to be created
        here.  Creating it only when absent is not enough: a rebuild (`stack prepare`)
        moves `:stack` to a new image while the deployment tag still names the old one,
        which would silently keep running the previous build.  So re-tag whenever the two
        names disagree, which is also the edit-build-restart loop for a compose deployment
        (see docs/developing-applications.md).
        """
        for compose_file in self.compose_files:
            parsed_file = get_yaml().load(open(compose_file, "r"))
            for svc_name in parsed_file.get("services", {}):
                image = parsed_file["services"][svc_name].get("image")
                if not image or not image.endswith(self.deployment_context.id):
                    continue
                stack_image = image.replace(f":{self.deployment_context.id}", ":stack")
                stack_image_id = _local_image_id(stack_image)
                if stack_image_id is None:
                    # No locally built image: the staged tag is all there is to run.
                    if _local_image_id(image) is not None:
                        continue
                    error_exit(f"Cannot find {image} or {stack_image} locally. Did you run 'stack prepare'?")
                if stack_image_id == _local_image_id(image):
                    continue
                log_info(f"Tagging {stack_image} to {image}...")
                self.docker.tag(stack_image, image)

    def _export_referenced_secrets(self):
        """Resolve referenced secrets and export them for compose interpolation.

        The generated compose files consume each one as ${STACK_SECRET_<name>:-},
        so the value exists only in this process's environment for the length of
        the command, never in the deployment directory.  Generated secrets are
        not handled here: they persist in secrets.env, which the services read as
        an env_file.
        """
        spec = getattr(self.deployment_context, "spec", None) if self.deployment_context else None
        if not spec:
            return
        for name, value in stack_secrets.resolve_referenced_secrets(spec).items():
            os.environ[stack_secrets.shell_var(name)] = value

    def up(self, detach, skip_cluster_management, services):
        if not opts.o.dry_run:
            self._stage_local_images()
            self._export_referenced_secrets()
            try:
                return self.docker.compose.up(detach=detach, services=services)
            except DockerException as e:
                raise DeployerException(e)

    def down(self, timeout):
        if not opts.o.dry_run:
            try:
                return self.docker.compose.down(timeout=timeout)
            except DockerException as e:
                raise DeployerException(e)

    def destroy(self, timeout, delete_volumes, delete_certificate, skip_cluster_management):
        """Stop the deployment and remove its volume objects.

        There is no certificate of stack's own to collect here: TLS on this
        target is the docker-ingress stack's business, and its certificates live
        in its own volume (see docs/ingress.md).  Removing a named volume
        removes the volume object, never a bind-mounted directory's contents --
        the same thing it has always meant on this target.
        """
        if not opts.o.dry_run:
            try:
                return self.docker.compose.down(timeout=timeout, volumes=delete_volumes)
            except DockerException as e:
                raise DeployerException(e)

    def update(self):
        """Converge the running deployment on its deployment directory.

        Re-pointing the deployment's private image tags picks up rebuilds, and
        `compose up` recreates exactly the containers whose image or resolved
        configuration (including config.env, folded in as an env_file) changed,
        naming them in its output.  A plain restart would apply neither: it
        reuses the existing containers, environment and all.
        """
        if not opts.o.dry_run:
            self._stage_local_images()
            self._export_referenced_secrets()
            try:
                return self.docker.compose.up(detach=True)
            except DockerException as e:
                raise DeployerException(e)

    def status(self):
        if not opts.o.dry_run:
            try:
                for p in self.docker.compose.ps():
                    output_main(f"{p.name}\t{p.state.status}")
            except DockerException as e:
                raise DeployerException(e)
            self._output_volume_status()

    def _output_volume_status(self):
        """Report where each of the deployment's volumes actually keeps its data.

        Read from Docker rather than from the spec because the volume is what
        the containers use: a spec volume edited after `deploy` names a
        directory nothing is mounting, and the volume goes on pointing at the
        one it was created with.  Every volume stack generates for a mapped
        path is a `local` volume bind-mounted at `device`, so that option is
        the host directory; an unmapped volume has no device and its data sits
        under Docker's own mountpoint.
        """
        try:
            volumes = self.docker.volume.list(
                filters={"label": f"com.docker.compose.project={self.compose_project_name}"}
            )
        except DockerException as e:
            raise DeployerException(e)

        if not volumes:
            return

        output_main("")
        output_main("Volumes:")
        for volume in sorted(volumes, key=lambda v: v.name):
            # The name the stack knows it by, not the project-prefixed one Docker made.
            name = volume.labels.get("com.docker.compose.volume", volume.name)
            path = (volume.options or {}).get("device") or volume.mountpoint
            output_main(f"\t{name}: {path}")

    def ps(self):
        if not opts.o.dry_run:
            try:
                return self.docker.compose.ps()
            except DockerException as e:
                raise DeployerException(e)

    def port(self, service, private_port):
        if not opts.o.dry_run:
            try:
                return self.docker.compose.port(service=service, private_port=private_port)
            except DockerException as e:
                raise DeployerException(e)

    def execute(self, service, command, tty, envs):
        if not opts.o.dry_run:
            try:
                return self.docker.compose.execute(service=service, command=command, tty=tty, envs=envs)
            except DockerException as e:
                raise DeployerException(e)

    def logs(self, services, tail, follow, stream):
        if not opts.o.dry_run:
            try:
                return self.docker.compose.logs(services=services, tail=tail, follow=follow, stream=stream)
            except DockerException as e:
                raise DeployerException(e)

    def _backup_exec(self, command, envs=None):
        """Run one of the backup container's scripts and return its output.

        On this target the backup engine is the mixed-in backup service, which
        holds the restic configuration and the data volume mounts; every backup
        operation is therefore a script in that container rather than something
        this process does itself.
        """
        try:
            return self.docker.compose.execute(
                service=constants.backup_service_name,
                command=command,
                tty=False,
                envs=envs or {},
            )
        except DockerException as e:
            raise DeployerException(e)

    def backup_now(self):
        if not opts.o.dry_run:
            output_main(self._backup_exec(["/scripts/backup.sh"]))

    def backup_list(self):
        if opts.o.dry_run:
            return []
        snapshots = []
        # One tab-separated "<id> <date> <volume,volume>" line per snapshot; see
        # list.sh in the backup-stack repo.
        for line in (self._backup_exec(["/scripts/list.sh"]) or "").splitlines():
            fields = line.split("\t")
            if len(fields) != 3:
                continue
            snapshots.append(
                {
                    "id": fields[0],
                    "date": fields[1],
                    "volumes": [v for v in fields[2].split(",") if v],
                }
            )
        return snapshots

    def backup_restore(self, snapshot, volumes, source=None):
        if opts.o.dry_run:
            return
        envs = {}
        if source:
            # The engine builds its repository from BACKUP_S3_*, but honours a
            # RESTIC_REPOSITORY it is given -- so pointing this one run at another
            # deployment's repository needs nothing of the container but the
            # environment it is handed. The deployment's own configuration, and so
            # where its next backup goes, is untouched.
            settings = backup_settings()
            envs["RESTIC_REPOSITORY"] = f"s3:{settings.s3_endpoint.rstrip('/')}/{settings.s3_bucket.rstrip('/')}/{source}"
        output_main(self._backup_exec(["/scripts/restore.sh", snapshot or "latest"] + list(volumes or []), envs=envs))

    def read_secrets(self):
        return stack_secrets.local_secret_values(self.deployment_context.spec, self.deployment_context.deployment_dir)

    def run(
        self,
        image: str,
        command=None,
        user=None,
        volumes=None,
        entrypoint=None,
        env=None,
        ports=None,
        detach=False,
    ):
        if not env:
            env = {}

        if not ports:
            ports = []

        if not opts.o.dry_run:
            try:
                return self.docker.run(
                    image=image,
                    command=command,
                    user=user,
                    volumes=volumes,
                    entrypoint=entrypoint,
                    envs=env,
                    detach=detach,
                    publish=ports,
                    publish_all=len(ports) == 0,
                )
            except DockerException as e:
                raise DeployerException(e)


class DockerDeployerConfigGenerator(DeployerConfigGenerator):
    def __init__(self, type: str, deployment_context: DeploymentContext) -> None:
        super().__init__()
        self.deployment_context = deployment_context

    def generate(self, deployment_dir: Path):
        with open(self.deployment_context.get_env_file(), "ta") as env_file:
            print(f'STACK_HOST_UID="{os.getuid()}"', file=env_file)
            print(f'STACK_HOST_GID="{os.getgid()}"', file=env_file)
        # Mint any generated secrets into secrets.env now, so the file the
        # generated compose files name as an env_file exists before any compose
        # command parses them.
        stack_secrets.ensure_generated_secrets(self.deployment_context.spec, deployment_dir)
