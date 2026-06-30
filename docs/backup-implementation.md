# Backup — implementation sketch

> **Status: design sketch — not yet implemented.** Companion to [backup.md](./backup.md). This pins the
> design down to concrete functions and insertion points in the existing code, mirroring how ingress is
> implemented, so the work can be reviewed before it is written. Code below is illustrative, not final.

## Scope of this sketch

This covers the **deploy-time injection pass** (the first concrete step) and the two things it depends on:

1. parsing the `@stack backup-*` annotations into the spec (mirrors `Stack.get_http_proxy_targets`);
2. an accessor for that spec section (mirrors `Spec.get_http_proxy`);
3. injecting a backup service into the generated deployment at deploy time (mirrors the
   `VIRTUAL_HOST_MULTIPORTS` injection).

**Out of scope here** (later steps): the `bozemanpass/backup-stack` container image, the
`stack manage … backup` subcommands, and the Kubernetes K8up-resource emission. Those are tracked in
[backup.md](./backup.md).

## The ingress pattern we are mirroring

For reference, ingress works in three touch-points, all of which have a backup analogue:

| Ingress                                                   | Backup analogue                                            |
| --------------------------------------------------------- | --------------------------------------------------------- |
| `Stack.get_http_proxy_targets()` parses port annotations (`stack.py:203`) | `Stack.get_backup_targets()` parses volume/service annotations |
| targets written into `network.http-proxy` spec section    | targets written into a `backup` spec section              |
| `Spec.get_http_proxy()` accessor (`spec.py:140`)          | `Spec.get_backup()` accessor                              |
| inject `VIRTUAL_HOST_MULTIPORTS` env at deploy (`deployment_create.py:550`) | inject a `backup` service + `:ro` mounts at deploy |

## 1. Parse annotations — `deploy/stack.py`

Add a method alongside `get_http_proxy_targets` (`stack.py:203`). Unlike ingress, backup annotations attach
to two different places — a **volume mount line** (`backup-exclude`) and a **service** (`backup-command`,
`backup-file-extension`). Both are read from `ruamel`'s comment attributes (`.ca`), exactly as the ingress
parser reads port-line comments.

```python
# constants.py (new)
backup_key = "backup"
backup_exclude_annotation = "backup-exclude"
backup_command_annotation = "backup-command"
backup_file_extension_annotation = "backup-file-extension"

# deploy/stack.py — new method on Stack
def get_backup_targets(self):
    """Parse @stack backup-* annotations from the stack's composefiles.

    Returns {"exclude": [volume_name, ...],
             "commands": {service_name: {"command": str, "file_extension": str}}}
    """
    exclude = []
    commands = {}
    for pod in self.get_pod_list():
        parsed_pod_file = self.load_pod_file(pod)
        for svc_name, svc in parsed_pod_file.get(constants.services_key, {}).items():
            # Service-level annotations (backup-command / backup-file-extension) live in the
            # comment block attached to the service mapping.
            for ann in _stack_annotations_for(svc):       # small helper over svc.ca
                if constants.backup_command_annotation in ann:
                    commands.setdefault(svc_name, {})["command"] = _annotation_value(ann)
                elif constants.backup_file_extension_annotation in ann:
                    commands.setdefault(svc_name, {})["file_extension"] = _annotation_value(ann)

            # Volume-level annotation (backup-exclude) lives on the mount line, like ports do.
            volumes_section = svc.get(constants.volumes_key, [])
            for i, mount in enumerate(volumes_section):
                comment = _line_comment(volumes_section, i)   # mirrors ports_section.ca.items[i]
                if comment and constants.stack_annotation_marker in comment \
                        and constants.backup_exclude_annotation in comment:
                    exclude.append(str(mount).split(":")[0])
    return {"exclude": exclude, "commands": commands}
```

`_line_comment()` is the same `ports_section.ca.items[i][0].value` access used at `stack.py:213-215`,
factored out so it can be reused for the volumes list.

## 2. Spec section + accessor — `deploy/spec.py`

The parsed targets are written into a top-level `backup` section of the spec during `stack init` (alongside
where `http-proxy` targets are written, `deployment_create.py:285-326`). Add the read accessor next to
`get_http_proxy` (`spec.py:140`):

```python
# deploy/spec.py
def get_backup(self):
    return self.obj.get(constants.backup_key, {})
```

Because `backup` is a plain dict it merges additively across mixed-in specs with no special handling, like
the other spec sections.

## 3. Augment the backup service at deploy time — `deploy/deployment_create.py`

This is the core of the pass, and it follows the ingress model exactly: the **backup service is defined in
the `backup-stack` repo** (`backup/composefile.yml`), and the deploy step only *augments* it — appending the
read-only data-volume mounts and setting the backup environment — just as ingress augments the existing
`nginx` service with `VIRTUAL_HOST_MULTIPORTS`. We do **not** fabricate the service in Python, so its
definition (image, Docker-socket mount, restic cache volume, entrypoint) lives in one place.

The augment runs inside the **existing** per-pod service loop, right next to the `VIRTUAL_HOST_MULTIPORTS`
injection (`deployment_create.py:550-574`), firing only for the `backup` service when the master switch is
on. **Current state:** the `backup-stack` must be mixed in explicitly (an extra `--spec-file`), exactly as
the ingress stack is today; auto-including it when the switch is on is a planned refinement, not yet built.
The implemented form:

```python
# deploy/deployment_create.py — within the `for service_name in services:` loop,
# alongside the VIRTUAL_HOST_MULTIPORTS block (~line 550)

from stack.config.util import get_config_setting

if get_config_setting("backup", False) and service_name == constants.backup_service_name:
    backup_cfg = parsed_spec.get_backup()
    exclude = set(backup_cfg.get("exclude", []))

    # Append a read-only mount for every (non-excluded) data volume to the service the
    # backup-stack composefile already defines. On Docker each named volume is a bind mount
    # under <deployment-dir>/data/<name>/ (`_fixup_pod_file`, line 77), so we mount those host
    # paths directly and avoid re-declaring named volumes across compose files.
    mounts = service_info.setdefault("volumes", [])
    for v, vol_path in parsed_spec.get_volumes().items():
        if v in exclude or not vol_path:
            continue
        device = vol_path if Path(vol_path).is_absolute() else f".{vol_path}"  # same path the volume binds to
        mounts.append(f"{device}:/backup/{v}:ro")

    # Consistency-dump hooks: "service:command:ext;...". Executed inside the target container
    # via the Docker socket the backup service already mounts (mirrors K8up's backupcommand).
    pre_hooks = [
        f"{svc}:{c['command']}:{c.get('file_extension', 'dump')}"
        for svc, c in backup_cfg.get("commands", {}).items()
    ]

    svc_env = service_info.get("environment", {})
    add_env_var("BACKUP_S3_ENDPOINT", get_config_setting("backup-s3-endpoint"), svc_env)
    add_env_var("BACKUP_S3_BUCKET", get_config_setting("backup-s3-bucket"), svc_env)
    add_env_var("BACKUP_SCHEDULE", get_config_setting("backup-schedule", "0 3 * * *"), svc_env)
    add_env_var("BACKUP_RETENTION",
                get_config_setting("backup-retention",
                                   "--keep-daily 7 --keep-weekly 4 --keep-monthly 6"), svc_env)
    add_env_var("BACKUP_PRE_HOOKS", ";".join(pre_hooks), svc_env)
    service_info["environment"] = svc_env
```

`constants.backup_service_name` is `"backup"` — the service name in `backup-stack/backup/composefile.yml`.
The `restic-password` and S3 credentials are *not* set here: they arrive via the shared `config.env`
(`env_file`) already injected into every service at `deployment_create.py:538-548`, so no new secret path
is introduced.

Notes:

- **One mount per volume, `:ro`.** This matches the doc and lets restic see a clean per-volume tree. A
  simpler variant is a single `../data:/backup:ro` mount with restic `--exclude` patterns; either works.
- **`restic-password` and the S3 credentials** arrive via the shared `config.env` (`env_file`), which is
  how `get_config_setting` values already reach containers — no new secret-plumbing path is introduced.
- **Consistency hooks run via the Docker socket**, which the `backup` service mounts in
  `backup-stack/backup/composefile.yml`. The hook runner `docker exec`s the dump command inside the target
  service container (resolved by compose label), mirroring K8up's exec-into-the-pod model — so no database
  clients need to be baked into the backup image.
- The backup service appears in `stack manage … ps` like any other container, which is what the
  forthcoming `backup` subcommands will `exec` into.

## What this deliberately does *not* do yet

- The `bozemanpass/backup` image exists as an **initial scaffold** in the `backup-stack` repo (its
  `Containerfile`, `build.sh`, and `scripts/` for entrypoint, cron, hook runner, and restore) but has not
  been run end-to-end and is not yet wired into a build.
- The deploy-time augment above is **not yet implemented in code** — this document is still the spec for it.
- It does not emit anything on the Kubernetes target; that path generates a K8up `Schedule` + annotations
  and is a sibling to this function.
- It does not add the `stack manage … backup` subcommands.

These are intentionally separable: this pass produces a deployment whose `backup` service *declares* its
backup intent (its `:ro` data mounts and env) in the generated compose, which is the foundation the
remaining pieces build on.
