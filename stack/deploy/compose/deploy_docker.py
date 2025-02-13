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

from pathlib import Path
from python_on_whales import DockerClient, DockerException
from stack.deploy.deployer import Deployer, DeployerException, DeployerConfigGenerator
from stack.deploy.deployment_context import DeploymentContext
from stack.opts import opts
from stack.util import get_yaml


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

    def up(self, detach, skip_cluster_management, services):
        if not opts.o.dry_run:
            try:
                return self.docker.compose.up(detach=detach, services=services)
            except DockerException as e:
                raise DeployerException(e)

    def down(self, timeout, volumes, skip_cluster_management):
        if not opts.o.dry_run:
            try:
                return self.docker.compose.down(timeout=timeout, volumes=volumes)
            except DockerException as e:
                raise DeployerException(e)

    def update(self):
        if not opts.o.dry_run:
            try:
                return self.docker.compose.restart()
            except DockerException as e:
                raise DeployerException(e)

    def status(self):
        if not opts.o.dry_run:
            try:
                for p in self.docker.compose.ps():
                    print(f"{p.name}\t{p.state.status}")
            except DockerException as e:
                raise DeployerException(e)

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


def env_var_name_for_service(svc_name):
    return f"STACK_SVC_{svc_name.upper()}".replace("-", "_")


class DockerDeployerConfigGenerator(DeployerConfigGenerator):
    def __init__(self, type: str, deployment_context: DeploymentContext) -> None:
        super().__init__()
        self.deployment_context = deployment_context

    # Nothing needed at present for the docker deployer
    def generate(self, deployment_dir: Path):
        yaml = get_yaml()
        compose_files = self.deployment_context.get_compose_files()

        all_service_names = []
        for f in compose_files:
            compose = yaml.load(open(f, "r"))
            if "services" in compose:
                services = compose["services"]
                for svc in services:
                    all_service_names.append(svc)

        with open(self.deployment_context.get_env_file(), "ta") as env_file:
            for svc_name in all_service_names:
                print(f'{env_var_name_for_service(svc_name)}="{svc_name}"', file=env_file)
