"""OpenCode adapter — generates native opencode.json at launch.

Injection path: OPENCODE_CONFIG env var. Maps ToolKind → native permission
keys (read/grep/glob/list for READ+SEARCH, edit/write/patch for EDIT,
bash for EXECUTE). PermissionMode values map 1:1 to OpenCode's
"allow"/"ask"/"deny".
Reference: MDSBAOS-141, PRD-6
"""

from __future__ import annotations

import json
import logging

from ...models import AgentSessionConfig
from ...protocol.enums import PermissionMode, ToolKind
from ..acp_adapter import ACPAgentAdapter
from ..launch_config import (
    LaunchAdjustment,
    config_fingerprint,
    is_trivial_config,
    launch_config_path,
    resolve_mode,
)

logger = logging.getLogger(__name__)


_SCOPE_TO_TOOLS = {
    ToolKind.READ: ["read"],
    ToolKind.SEARCH: ["grep", "glob", "list"],
    ToolKind.EDIT: ["edit", "write", "patch"],
    ToolKind.EXECUTE: ["bash"],
}


NAUTEX_AGENT_ID = "nautex-coding"


class OpenCodeAdapter(ACPAgentAdapter):
    def _prepare_launch(self, config: AgentSessionConfig) -> LaunchAdjustment:
        """Generate opencode.json for ACP session.

        OpenCode's top-level `permission` acts as a baseline, but each built-in
        agent (build/plan/…) can override it. `opencode acp` activates a primary
        agent and that agent's permissions win, so we define our own primary
        `nautex-coding` and pin it via top-level `default_agent`. The same
        policy is mirrored at top-level for safety.
        """
        if is_trivial_config(config):
            return LaunchAdjustment()
        fp = config_fingerprint(self._agent_id, self._directory_scope, config)
        config_path = launch_config_path(self._agent_id, fp, ".json")

        # Only write scopes with an explicit override; DEFAULT is omitted so
        # OpenCode falls back to its own configured policy for that tool.
        permission: dict = {}
        for kind, tools in _SCOPE_TO_TOOLS.items():
            mode = resolve_mode(config.permissions, kind)
            if mode == PermissionMode.DEFAULT:
                continue
            for tool in tools:
                permission[tool] = mode.value

        mcp: dict = {}
        for m in config.mcp_servers:
            mcp[m.server_id] = {
                "type": "local",
                "command": m.command,
                "args": list(m.args),
                "environment": dict(m.env),
            }

        instructions = []
        if config.system_prompt_extension:
            prompt_path = launch_config_path(self._agent_id, fp, ".prompt.md")
            prompt_path.write_text(config.system_prompt_extension, encoding="utf-8")
            instructions.append(str(prompt_path))

        opencode_config = {
            "$schema": "https://opencode.ai/config.json",
            "permission": permission,
            "mcp": mcp,
            "instructions": instructions,
            "default_agent": NAUTEX_AGENT_ID,
            "agent": {
                NAUTEX_AGENT_ID: {
                    "mode": "primary",
                    "permission": permission,
                },
                # Also pin build (OpenCode's canonical default) in case any
                # path falls back to it before our default_agent resolves.
                "build": {
                    "permission": permission,
                },
            },
        }
        config_path.write_text(json.dumps(opencode_config, indent=2), encoding="utf-8")
        logger.info("OpenCode config generated: %s (default_agent=%s)", config_path, NAUTEX_AGENT_ID)

        return LaunchAdjustment(extra_env={"OPENCODE_CONFIG": str(config_path)})
