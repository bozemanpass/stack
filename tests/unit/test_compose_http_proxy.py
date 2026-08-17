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

"""What a compose deployment tells nginx-proxy about its HTTP routes.

The Docker target has no ingress of its own: the http-proxy section of the spec
becomes VIRTUAL_HOST_MULTIPORTS and LETSENCRYPT_HOST environment variables on the
proxied services, and the nginx-proxy container of the docker-ingress stack turns
those into nginx configuration (see docs/ingress.md).

Regression coverage: a non-root route used to be emitted as an nginx regex
location, "~ ^/api/todos(?:/(.*))?$", with a destination of /$1. nginx-proxy reads
these keys as path prefixes and skips any that does not start with "/", so the
route was dropped from the generated configuration silently -- the service was up
and healthy and answered nothing, because requests for it landed on whichever
route did survive. Prefix stripping belongs in the destination instead, which is
nginx's own mechanism for it.

Nothing here needs a docker daemon: deploying a compose deployment writes files.
"""

import json

import yaml

from conftest import make_stack_from_compose, run_stack

FQDN = "todo.example.com"

# Two services on one hostname, told apart by path -- the arrangement the
# annotations exist for, and the one that broke.
PROXIED_POD = """\
    services:
      frontend:
        image: frontend:local
        ports:
          - "3000"  # @stack http-proxy /
      backend:
        image: backend:local
        ports:
          - "5000"  # @stack http-proxy /api/todos
    """


def deploy_proxied_stack(tmp_path, env, fqdn=FQDN):
    """Init and deploy the stack above, returning {service name: environment}."""
    stack_dir = make_stack_from_compose(tmp_path, PROXIED_POD)
    spec_file = tmp_path / "spec.yml"
    result = run_stack(
        ["init", "--stack", str(stack_dir), "--output", str(spec_file), "--http-proxy-fqdn", fqdn],
        env,
    )
    assert result.returncode == 0, result.stderr

    deployment_dir = tmp_path / "deployment"
    result = run_stack(
        ["deploy", "--spec-file", str(spec_file), "--deployment-dir", str(deployment_dir)],
        env,
    )
    assert result.returncode == 0, result.stderr

    compose_files = list((deployment_dir / "compose").glob("*.yml"))
    assert len(compose_files) == 1, f"expected one compose file, got {compose_files}"
    services = yaml.safe_load(compose_files[0].read_text())["services"]
    return {name: service.get("environment", {}) for name, service in services.items()}


def multiports(environment):
    return json.loads(environment["VIRTUAL_HOST_MULTIPORTS"])


def test_root_route_is_published_at_the_root_path(tmp_path, isolated_env):
    environments = deploy_proxied_stack(tmp_path, isolated_env)
    assert multiports(environments["frontend"]) == {FQDN: {"/": {"dest": "/", "port": "3000"}}}


def test_sub_path_route_is_a_prefix_that_strips_itself(tmp_path, isolated_env):
    # A plain prefix, not a regex: nginx-proxy skips a key that does not begin with
    # "/", and the "/" destination is what makes the service see /1 rather than
    # /api/todos/1.
    environments = deploy_proxied_stack(tmp_path, isolated_env)
    assert multiports(environments["backend"]) == {FQDN: {"/api/todos": {"dest": "/", "port": "5000"}}}


def test_each_proxied_service_is_told_the_certificate_hostname(tmp_path, isolated_env):
    # What the acme companion in the docker-ingress stack watches for.
    environments = deploy_proxied_stack(tmp_path, isolated_env)
    assert environments["frontend"]["LETSENCRYPT_HOST"] == FQDN
    assert environments["backend"]["LETSENCRYPT_HOST"] == FQDN


def test_localhost_asks_for_no_certificate(tmp_path, isolated_env):
    # No certificate authority will issue for "localhost", and asking makes the
    # companion retry forever, so a local deployment is routed but not secured.
    environments = deploy_proxied_stack(tmp_path, isolated_env, fqdn="localhost")
    assert multiports(environments["frontend"]) == {"localhost": {"/": {"dest": "/", "port": "3000"}}}
    assert "LETSENCRYPT_HOST" not in environments["frontend"]
    assert "LETSENCRYPT_HOST" not in environments["backend"]
