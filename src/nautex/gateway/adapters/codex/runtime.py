"""Codex CLI adapter — injects config via `-c key=value` CLI overrides.

sandbox_mode derives from EDIT/EXECUTE modes; approval_policy is "never"
when every scope is ALLOW, else "on-request". The gateway's permission
wrapper still hard-denies scopes set to DENY before the request reaches
either Codex's own sandbox or the user.
Reference: MDSBAOS-141, PRD-6
"""

from __future__ import annotations

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


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\"", "\\\"")


def _resolve_sandbox_mode(config: AgentSessionConfig) -> str:
    """workspace-write when EDIT or EXECUTE is not DENY, else read-only."""
    for kind in (ToolKind.EDIT, ToolKind.EXECUTE):
        if resolve_mode(config.permissions, kind) != PermissionMode.DENY:
            return "workspace-write"
    return "read-only"


def _resolve_approval_policy(config: AgentSessionConfig) -> str:
    """Prompt only when a scope is explicitly ASK; otherwise "never".

    Codex-specific tradeoff (verified 2026-04, codex-acp 0.11.1):

    DENY scope is enforced via sandbox_mode, NOT via permission requests. The
    reason: Codex's patch_approval ships only two options — "approved"
    (allow_once) and "abort" (reject_once, labeled "No, and tell Codex what
    to do differently"). Selecting "abort" is interpreted as aborting the
    whole turn (stop_reason=cancelled), so the agent stops iterating. With
    approval_policy="never", Codex skips the permission step entirely: the
    sandbox blocks the tool internally, the agent sees an error in tool
    output, narrates it in the message, and the turn completes naturally
    (stop_reason=end_turn).

    Consequence: for DENY we get no tool_call or permission items in the chat
    (Codex emits only agent_message_chunk in this mode). Visibility comes
    from the agent's narration. If we ever need widget visibility, switch
    back to "on-request" and accept turn cancellation on edit/patch denials.
    """
    for kind in (ToolKind.READ, ToolKind.SEARCH, ToolKind.EDIT, ToolKind.EXECUTE):
        if resolve_mode(config.permissions, kind) == PermissionMode.ASK:
            return "on-request"
    return "never"


class CodexAdapter(ACPAgentAdapter):
    def _prepare_launch(self, config: AgentSessionConfig) -> LaunchAdjustment:
        if is_trivial_config(config):
            return LaunchAdjustment()
        fp = config_fingerprint(self._agent_id, self._directory_scope, config)

        overrides: list = [
            f'sandbox_mode="{_resolve_sandbox_mode(config)}"',
            f'approval_policy="{_resolve_approval_policy(config)}"',
            f'sandbox_workspace_write.network_access={"true" if resolve_mode(config.permissions, ToolKind.EXECUTE) != PermissionMode.DENY else "false"}',
        ]

        if config.system_prompt_extension:
            prompt_path = launch_config_path(self._agent_id, fp, ".prompt.md")
            prompt_path.write_text(config.system_prompt_extension, encoding="utf-8")
            overrides.append(f'model_instructions_file="{_toml_escape(str(prompt_path))}"')

        for m in config.mcp_servers:
            overrides.append(f'mcp_servers.{m.server_id}.command="{_toml_escape(m.command)}"')
            if m.args:
                args_toml = ", ".join(f'"{_toml_escape(a)}"' for a in m.args)
                overrides.append(f'mcp_servers.{m.server_id}.args=[{args_toml}]')

        extra_args: list = []
        for kv in overrides:
            extra_args.extend(["-c", kv])

        logger.info("Codex launch config via -c: %d overrides", len(overrides))
        return LaunchAdjustment(extra_args=extra_args)
