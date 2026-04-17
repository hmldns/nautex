"""Claude Code adapter — generates settings.json + .mcp.json + prompt.md.

ToolKind maps to Claude's native tool names: READ→Read, SEARCH→Glob+Grep,
EDIT→Edit+Write+NotebookEdit, EXECUTE→Bash.

Claude-specific override: `_permission_response_mapper` returns a non-spec
"soft deny" response on DENY. Claude interprets spec-correct
`AllowedOutcome(option_id=<reject_once>, outcome="selected")` as a decisive
user rejection and ends the turn silently. Returning a malformed
`AllowedOutcome(option_id="denied", outcome="denied")` (bypasses pydantic
validation via `model_construct`) makes Claude treat the response as a tool
error, narrate the failure, and try alternative tools before ending the
turn. This preserves visibility without approving the denied action —
Claude still can't execute the denied tool because each retry also gets
denied by our policy callback.
Reference: MDSBAOS-141, PRD-6
"""

from __future__ import annotations

import json
import logging

import acp
from acp.schema import AllowedOutcome

from ...models import AgentSessionConfig
from ...protocol import PermissionAction
from ...protocol.enums import PermissionMode, ToolKind
from ..acp_adapter import ACPAgentAdapter
from ..acp_client import _map_response_to_acp
from ..launch_config import (
    LaunchAdjustment,
    config_fingerprint,
    is_trivial_config,
    launch_config_path,
    resolve_mode,
)

logger = logging.getLogger(__name__)


_SCOPE_TO_TOOLS = {
    ToolKind.READ: ["Read"],
    ToolKind.SEARCH: ["Glob", "Grep"],
    ToolKind.EDIT: ["Edit", "Write", "NotebookEdit"],
    ToolKind.EXECUTE: ["Bash"],
}


def _claude_response_mapper(action: PermissionAction, options: list) -> "acp.RequestPermissionResponse":
    """Claude-specific PermissionAction → ACP response mapping.

    APPROVE: falls back to the spec-correct default.
    DENY: returns a non-spec `AllowedOutcome(option_id="denied", outcome="denied")`
    via `model_construct` (bypasses pydantic's Literal validation). Claude
    treats this as a tool-level error, which keeps the turn alive — agent
    narrates the failure and tries alternative tools. Each alternative also
    hits our policy callback and receives the same soft-no, so nothing
    denied actually executes; we just avoid the silent stop.
    """
    if action == PermissionAction.APPROVE:
        return _map_response_to_acp(action, options)
    logger.info("[claude_code] soft-deny response (non-spec denied/denied)")
    outcome = AllowedOutcome.model_construct(option_id="denied", outcome="denied")
    return acp.RequestPermissionResponse.model_construct(outcome=outcome)


class ClaudeAdapter(ACPAgentAdapter):
    def _permission_response_mapper(self):
        return _claude_response_mapper

    def _prepare_launch(self, config: AgentSessionConfig) -> LaunchAdjustment:
        if is_trivial_config(config):
            return LaunchAdjustment()
        fp = config_fingerprint(self._agent_id, self._directory_scope, config)

        # Canonical mapping: ALLOW→allow[], ASK→ask[], DENY→deny[].
        # (The "soft deny" handling that keeps the turn alive lives in
        # _claude_response_mapper above — the settings.json layer stays
        # straightforward.)
        allow: list = []
        ask: list = []
        deny: list = []
        bucket_for_mode = {
            PermissionMode.ALLOW: allow,
            PermissionMode.ASK: ask,
            PermissionMode.DENY: deny,
        }
        all_allow = True
        for kind, tools in _SCOPE_TO_TOOLS.items():
            mode = resolve_mode(config.permissions, kind)
            if mode == PermissionMode.DEFAULT:
                all_allow = False
                continue
            if mode != PermissionMode.ALLOW:
                all_allow = False
            bucket_for_mode[mode].extend(tools)

        settings = {
            "permissions": {
                "allow": allow,
                "ask": ask,
                "deny": deny,
                "defaultMode": "dontAsk" if all_allow else "default",
            },
        }
        settings_path = launch_config_path(self._agent_id, fp, ".settings.json")
        settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

        mcp_entries = {}
        for m in config.mcp_servers:
            mcp_entries[m.server_id] = {
                "type": "stdio",
                "command": m.command,
                "args": list(m.args),
                "env": dict(m.env),
            }
        mcp_path = launch_config_path(self._agent_id, fp, ".mcp.json")
        mcp_path.write_text(json.dumps({"mcpServers": mcp_entries}, indent=2), encoding="utf-8")

        extra_args = ["--settings", str(settings_path), "--mcp-config", str(mcp_path)]

        if config.system_prompt_extension:
            prompt_path = launch_config_path(self._agent_id, fp, ".prompt.md")
            prompt_path.write_text(config.system_prompt_extension, encoding="utf-8")
            extra_args += ["--append-system-prompt-file", str(prompt_path)]

        logger.info("Claude Code config generated: %s (+mcp, +prompt)", settings_path)
        return LaunchAdjustment(extra_args=extra_args)
