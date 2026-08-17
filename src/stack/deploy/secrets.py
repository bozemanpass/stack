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

"""Secrets a deployed stack's containers need, kept out of its artifacts.

A stack declares in stack.yml *which* environment variables are secret:

    secrets:
      POSTGRES_PASSWORD:
      STRIPE_API_KEY:
        external: true

The spec then records, per secret, where its *value* comes from -- never the
value itself:

    secrets:
      POSTGRES_PASSWORD: generate
      STRIPE_API_KEY: env:STRIPE_KEY

`generate` means stack mints a random value at deploy time and nobody ever
supplies or sees it -- the right thing for a credential shared between two
containers of the same deployment (a database and its client) and meaningful
nowhere else.  It is the default for a declared secret; `external: true`
declares that a generated value would be useless (the counterpart is outside
the deployment) so the spec must name a reference.  References use the same
schemes as `kube-config` (see stack.deploy.references): `env:`, `file:`,
`env-file:`, and `exec:` as the escape hatch to any secret store.

Secrets are deployment-wide, exactly as the spec's `config` section is: every
container sees every secret.  What differs is the route to the container.
Config lands in `config.env` and in the generated artifacts in the clear;
a secret never appears in `spec.yml`, `config.env`, or a generated compose
file, and on Kubernetes it travels as a namespaced Secret referenced from the
container env rather than as a literal value in the Deployment object.

Generated values need to outlive a restart -- a database password is baked
into the database's volume.  Where they persist follows where the data does:
a remote cluster holds both (the Secret object lives in the namespace, beside
the PVCs), while compose and kind keep their data under the deployment
directory, so generated values sit beside it in `secrets.env` -- mode 0600 and
covered by a written .gitignore, since a deployment directory is frequently a
git repository.  Referenced values are never persisted anywhere: they are
resolved each time the deployment comes up.
"""

import os

from pathlib import Path
from secrets import token_hex

from stack import constants
from stack.deploy import references
from stack.util import error_exit, env_var_map_from_file

# The value marking a spec secret as minted at deploy time.
GENERATE = "generate"

# The one namespaced Secret holding all of a k8s deployment's secret env values.
K8S_SECRET_NAME = "stack-secrets"

# Referenced secrets reach docker compose through interpolation variables of
# this form, set in the deployer's environment for the duration of an up.
_SHELL_VAR_PREFIX = "STACK_SECRET_"


def shell_var(name: str) -> str:
    return f"{_SHELL_VAR_PREFIX}{name}"


def declared_secrets(stack) -> dict:
    """The stack's declared secrets, as {name: {..declaration..}}.

    A declaration with no body (`POSTGRES_PASSWORD:`) parses as None; normalize
    it to an empty dict so callers can .get() options off any entry.
    """
    declarations = stack.get(constants.secrets_key, {}) or {}
    return {name: (decl or {}) for name, decl in declarations.items()}


def validate_secret_entry(name, value):
    """Reject a spec secrets entry that could not produce a value at deploy time."""
    subject = f"secret {name}"
    if value == GENERATE:
        return
    if not references.is_reference(value):
        error_exit(
            f"{subject} must be '{GENERATE}' or a reference such as env:VAR_NAME, "
            f"file:PATH, env-file:VAR_NAME or exec:COMMAND -- secret values are "
            f"never stored in the spec (got: {value})"
        )
    references.validate_reference(value, subject, bare_meaning=f"'{GENERATE}'")


def validate_spec_secrets(spec):
    secret_entries = spec.get_secrets()
    for name, value in secret_entries.items():
        validate_secret_entry(name, value)
    # A key both in config and in secrets would reach the container twice with
    # different values, whichever wins; refuse the ambiguity instead.
    for name in secret_entries:
        if name in spec.get_config():
            error_exit(f"{name} is declared as a secret and may not also be set in config")


def generated_names(spec):
    return [name for name, value in spec.get_secrets().items() if value == GENERATE]


def referenced_entries(spec):
    return {name: value for name, value in spec.get_secrets().items() if value != GENERATE}


def new_secret_value() -> str:
    # Hex rather than a wider alphabet so the value embeds safely anywhere an
    # application might paste it -- a connection URL, a shell line, YAML.
    return token_hex(16)


def read_secrets_env(path: Path) -> dict:
    if not Path(path).exists():
        return {}
    return {k: v for k, v in env_var_map_from_file(path, expand=False).items() if v}


def _write_secrets_env(path: Path, values: dict):
    # Create 0600 before content goes in, rather than chmod after.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as output_file:
        for name, value in values.items():
            output_file.write(f"{name}={value}\n")


def _ensure_gitignored(deployment_dir: Path):
    gitignore = Path(deployment_dir).joinpath(".gitignore")
    line = constants.secrets_file_name
    if gitignore.exists() and line in gitignore.read_text().splitlines():
        return
    with open(gitignore, "a") as output_file:
        output_file.write(f"{line}\n")


def ensure_generated_secrets(spec, deployment_dir: Path) -> dict:
    """Mint any generated secrets this deployment is missing, and return them all.

    The store is `secrets.env` in the deployment directory -- used on the targets
    whose data also lives there (compose, kind), so a value a volume depends on
    survives exactly as long as the volume does.  Existing values are kept:
    minting is create-or-keep, never rotate.
    """
    names = generated_names(spec)
    if not names:
        return {}
    path = Path(deployment_dir).joinpath(constants.secrets_file_name)
    values = read_secrets_env(path)
    missing = [name for name in names if name not in values]
    for name in missing:
        values[name] = new_secret_value()
    if missing or not path.exists():
        _write_secrets_env(path, values)
        _ensure_gitignored(deployment_dir)
    return {name: values[name] for name in names}


def resolve_referenced_secrets(spec) -> dict:
    """Resolve every referenced secret to its current value, as {name: value}."""
    return {name: references.resolve_reference(value, f"secret {name}") for name, value in referenced_entries(spec).items()}


def local_secret_values(spec, deployment_dir: Path) -> dict:
    """The values this deployment's containers receive, on the local targets.

    On compose and kind the deployment directory is the store, so the answer
    needs no cluster: generated values read from secrets.env (None if not yet
    minted), referenced values resolved now -- which is exactly what the next
    up delivers.  Read-only: nothing is minted here.
    """
    stored = read_secrets_env(Path(deployment_dir).joinpath(constants.secrets_file_name))
    values = {name: stored.get(name) for name in generated_names(spec)}
    values.update(resolve_referenced_secrets(spec))
    return values
