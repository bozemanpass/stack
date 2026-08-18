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

"""Referential integrity checking for a stack's defining files.

The authority model (see docs/stack-integrity.md): a pod file's `image:` lines are
authoritative for what the stack *uses*, and the stack.yml `containers:` entries are
authoritative for how each locally built image is *made*.  The two are joined by the
image tag convention -- an image tagged with one of LOCALLY_BUILT_TAGS is an import
of a declared container, matched by name; any other image is external, pulled as the
pod file names it.  Everything else (the clone set, the lock contents) is derived.

This module checks that join: every import must have a declaration, and every
declaration should be imported.  It also flags the leftovers of the older, looser
model -- the hand-maintained `repos:` list and the per-pod `repository:` field --
which are deprecated because their content is now derived.
"""

import sys

import click

from pathlib import Path

from stack import constants
from stack.deploy.images import LOCALLY_BUILT_TAGS, split_image_reference
from stack.deploy.stack import Stack, get_parsed_stack_config, resolve_stack
from stack.log import log_error, log_warn, output_main
from stack.repos.repo_util import branch_strip

ERROR = "error"
WARNING = "warning"


class Finding:
    """One validation result: a severity, a short machine-ish code, and the message."""

    def __init__(self, severity: str, code: str, message: str):
        self.severity = severity
        self.code = code
        self.message = message

    def __repr__(self):
        return str(self)

    def __str__(self):
        return f"{self.severity}: {self.message} [{self.code}]"


def _declared_containers(stack: Stack, findings):
    """The container names stack.yml declares, appending findings for malformed entries."""
    declared = []
    for entry in stack.get("containers") or []:
        name = entry if isinstance(entry, str) else entry.get("name")
        if not name:
            findings.append(Finding(ERROR, "container-unnamed", "a containers: entry has no name"))
            continue
        if name in declared:
            findings.append(Finding(ERROR, "container-duplicate", f"container '{name}' is declared more than once"))
            continue
        declared.append(name)
    return declared


def _check_pod_images(stack: Stack, findings):
    """Parse every pod file, classifying each service's image.

    Returns (imported, has_pod_files): imported maps each locally-built image name to
    the "pod/service" locations importing it; has_pod_files is False when no pod file
    could be read at all (in which case usage checks would be vacuous)."""
    imported = {}
    has_pod_files = False
    for pod_name in stack.get_pod_list():
        pod_file_path = stack.get_pod_file_path(pod_name)
        if not pod_file_path or not Path(pod_file_path).exists():
            findings.append(Finding(ERROR, "pod-file-missing",
                                    f"pod '{pod_name}' names no readable pod file (looked at {pod_file_path})"))
            continue
        parsed_pod_file = stack.load_pod_file(pod_name)
        has_pod_files = True
        services = (parsed_pod_file or {}).get(constants.services_key) or {}
        for svc_name, svc in services.items():
            where = f"pod '{pod_name}' service '{svc_name}'"
            image = svc.get("image") if isinstance(svc, dict) else None
            if not image:
                findings.append(Finding(ERROR, "service-no-image", f"{where} has no image"))
                continue
            image = str(image)
            if "$" in image:
                findings.append(Finding(ERROR, "image-interpolation",
                                        f"{where}: image '{image}' uses variable interpolation; "
                                        f"images must be fully specified"))
                continue
            image_name, image_tag = split_image_reference(image)
            if image_tag in LOCALLY_BUILT_TAGS:
                imported.setdefault(image_name, []).append(where)
            elif image_tag is None and "@" not in image:
                findings.append(Finding(WARNING, "external-image-untagged",
                                        f"{where}: external image '{image}' has no tag (implicitly 'latest'); "
                                        f"name the version the stack is developed against"))
    return imported, has_pod_files


def _check_deprecated_pod_repository(stack: Stack, findings):
    # The per-pod repository: field let a stack borrow a pod file from another repo.
    # Loading injects the stack's own repo ref into every dict-form pod, so only a
    # value naming a *different* repo is an actual use of the feature.
    own_ref = stack.get_repo_ref()
    for pod in stack.get_pods():
        if not isinstance(pod, dict):
            continue
        pod_repository = pod.get("repository")
        if not pod_repository or pod_repository == "internal":
            continue
        if own_ref and branch_strip(pod_repository) == branch_strip(own_ref):
            continue
        findings.append(Finding(WARNING, "pod-repository-deprecated",
                                f"pod '{pod.get('name')}' takes its pod file from another repo ({pod_repository}); "
                                f"this is deprecated -- use a required stack instead (see docs/stack-integrity.md)"))


def _check_deprecated_repos(stack: Stack, findings):
    declared_repos = stack.get("repos") or []
    if not declared_repos:
        return
    findings.append(Finding(WARNING, "repos-deprecated",
                            "the repos: list is deprecated: the repos a stack needs are derived from its "
                            "container refs (see docs/stack-integrity.md)"))
    derivable = set()
    if stack.get_repo_ref():
        derivable.add(branch_strip(stack.get_repo_ref()))
    for entry in stack.get("containers") or []:
        if isinstance(entry, dict):
            for key in ("ref", "wrapper-ref"):
                if entry.get(key):
                    derivable.add(branch_strip(entry[key]))
    for repo in declared_repos:
        if branch_strip(repo) not in derivable:
            findings.append(Finding(WARNING, "repo-unreferenced",
                                    f"repos: entry '{repo}' is not the stack's own repo and is not referenced "
                                    f"by any container; nothing in the stack says why it is needed"))


def _validate_single_stack(stack: Stack):
    """Validate one (non-super) stack in isolation."""
    findings = []
    declared = _declared_containers(stack, findings)
    imported, has_pod_files = _check_pod_images(stack, findings)

    for image_name in sorted(imported):
        if image_name not in declared:
            locations = ", ".join(imported[image_name])
            findings.append(Finding(ERROR, "container-undeclared",
                                    f"{locations}: image '{image_name}' is tagged as locally built, but stack.yml "
                                    f"declares no container of that name"))
    # Without a readable pod file the usage side of the join is unknown, so silence
    # says nothing about a declaration.
    if has_pod_files:
        for name in declared:
            if name not in imported:
                findings.append(Finding(WARNING, "container-unused",
                                        f"container '{name}' is declared in stack.yml but no pod file uses "
                                        f"'{name}:stack'"))

    _check_deprecated_pod_repository(stack, findings)
    _check_deprecated_repos(stack, findings)
    return findings


def validate_stack(stack: Stack):
    """Validate a stack, following a super stack into each of its required stacks.

    Each required stack is validated in isolation: a child must be deployable on its
    own, so its pod files may only import containers it declares itself."""
    if not stack.is_super_stack():
        return _validate_single_stack(stack)

    findings = _validate_single_stack(stack)
    for child_path in stack.get_required_stacks_paths():
        if not Path(child_path).joinpath(constants.stack_file_name).exists():
            findings.append(Finding(WARNING, "required-stack-missing",
                                    f"required stack at {child_path} is not fetched, so it cannot be validated "
                                    f"(run 'stack fetch --stack {stack.name}' first)"))
            continue
        child = get_parsed_stack_config(Path(child_path))
        for finding in validate_stack(child):
            finding.message = f"[{child.name}] {finding.message}"
            findings.append(finding)
    return findings


def log_findings(stack: Stack):
    """Report findings as diagnostics: the migration-friendly form used inside other
    commands, which warns (on stderr) and never fails the enclosing command."""
    findings = validate_stack(stack)
    for finding in findings:
        if finding.severity == ERROR:
            log_error(f"ERROR: stack {stack.name}: {finding.message} [{finding.code}]")
        else:
            log_warn(f"WARN: stack {stack.name}: {finding.message} [{finding.code}]")
    return findings


@click.command()
@click.option("--stack", help="name or path of the stack", required=False)
@click.option("--strict", is_flag=True, default=False, help="treat warnings as errors")
@click.pass_context
def command(ctx, stack, strict):
    """check the stack's files for referential integrity"""
    parsed_stack = resolve_stack(stack)
    findings = validate_stack(parsed_stack)
    for finding in findings:
        output_main(str(finding))
    errors = [f for f in findings if f.severity == ERROR]
    warnings = [f for f in findings if f.severity == WARNING]
    if findings:
        output_main(f"{parsed_stack.name}: {len(errors)} error(s), {len(warnings)} warning(s)")
    else:
        output_main(f"{parsed_stack.name}: OK")
    if errors or (strict and warnings):
        sys.exit(1)
