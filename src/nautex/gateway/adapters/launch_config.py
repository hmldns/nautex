"""Launch-time config generation for agent adapters.

Per-agent adapters generate their native config files (opencode.json,
settings.json + mcp.json, config.toml) into `~/.nautex/configs/` with
deterministic hash-based names. The adapter returns a LaunchAdjustment
(env vars + CLI args) that the base applies to the spawn call.

Naming: cfg-launch-{agent_id}-{hash8}.{native_ext}
Hash is sha256(agent_id|cwd|config_json)[:8] — idempotent writes, no cleanup.
Cross-platform (uses pathlib.Path, no temp dirs).

Reference: MDSBAOS-141, PRD-6
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from ..models import AgentSessionConfig
from ..protocol.enums import PermissionMode, ToolKind


@dataclass
class LaunchAdjustment:
    """Per-agent launch-time modifications from generated native config.

    Files are persistent under ~/.nautex/configs/ with deterministic names,
    so no cleanup is required — re-running with the same inputs overwrites
    identical bytes.
    """
    extra_env: Dict[str, str] = field(default_factory=dict)
    extra_args: List[str] = field(default_factory=list)


def nautex_configs_dir() -> Path:
    """Return (and ensure) the persistent config dir ~/.nautex/configs/.

    Cross-platform: Path.home() resolves on Windows/Mac/Linux.
    """
    d = Path.home() / ".nautex" / "configs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_fingerprint(agent_id: str, cwd: str, config: AgentSessionConfig) -> str:
    """8-char sha256 fingerprint of (agent_id, cwd, config).

    Same inputs → same file name → idempotent writes. Credentials are
    excluded from the hash so rotating secrets doesn't invalidate the cache.
    """
    payload = f"{agent_id}|{cwd}|{config.model_dump_json(exclude={'credentials'})}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]


def launch_config_path(agent_id: str, fingerprint: str, suffix: str) -> Path:
    """Compose ~/.nautex/configs/cfg-launch-{agent}-{fp}{suffix}."""
    return nautex_configs_dir() / f"cfg-launch-{agent_id}-{fingerprint}{suffix}"


def resolve_mode(permissions: dict, kind: ToolKind) -> PermissionMode:
    """Look up the effective mode for a ToolKind; unset defaults to DEFAULT
    (i.e. no override — the adapter still surfaces to the user)."""
    return permissions.get(kind, PermissionMode.DEFAULT)


def is_trivial_config(config: AgentSessionConfig) -> bool:
    """True when nothing in the config would change the agent's native behavior.

    Used by per-agent _prepare_launch to skip native config file generation —
    the agent runs with its own defaults, env, and ~/.config files untouched.
    """
    if config.mcp_servers:
        return False
    if config.system_prompt_extension:
        return False
    # Any explicit mode (not DEFAULT) means we must generate a config.
    for mode in config.permissions.values():
        if mode != PermissionMode.DEFAULT:
            return False
    return True


def apply_implicit_permissions(config: AgentSessionConfig) -> AgentSessionConfig:
    """Pragmatic rule: if EDIT or EXECUTE is ALLOW, READ/SEARCH auto-elevate
    to ALLOW too. Writing needs reading; shelling needs path resolution. We
    only elevate for ALLOW — ASK/DENY/DEFAULT don't cascade.
    """
    perms = dict(config.permissions)
    writes = perms.get(ToolKind.EDIT) == PermissionMode.ALLOW
    exec_ok = perms.get(ToolKind.EXECUTE) == PermissionMode.ALLOW
    if not (writes or exec_ok):
        return config

    changed = False
    for kind in (ToolKind.READ, ToolKind.SEARCH):
        if perms.get(kind) != PermissionMode.ALLOW:
            perms[kind] = PermissionMode.ALLOW
            changed = True
    if not changed:
        return config
    return config.model_copy(update={"permissions": perms})
