"""Codex CLI adapter — config via env vars (codex-acp ≥ 1.x, agentclientprotocol scope).

The new bridge does not parse CLI arguments: its entrypoint only understands
`--version`, `login`, and `cli`. The old `-c key=value` override args from
the zed-industries bridge are silently ignored. Instead:

- INITIAL_AGENT_MODE selects an AgentMode preset ("read-only", "agent",
  "agent-full-access"). The preset supplies the per-turn approvalPolicy and
  sandboxPolicy and is the only launch-time permission lever the bridge
  exposes (verified applied via session/new modes.currentModeId).
- CODEX_CONFIG carries codex-core config.toml keys as JSON, spread into
  every session config by the bridge; used here for model_instructions_file.
- MCP servers are injected via ACP session/new; the bridge merges them into
  the session config itself.

KNOWN LIMITATION (verified 2026-07, codex-acp 1.1.0 / codex 0.142.5-0.143):
even in "read-only" mode, codex-core auto-approves gated actions through its
Guardian review (item/autoApprovalReview) instead of raising
session/request_permission, so DENY/ASK scopes are not enforced for locally
executed writes. Levers tried and defeated (see INTEGRATION_EFFORT_LOG.md):
--disable guardian_approval, features via CODEX_CONFIG, projects trust_level
override via wrapper -c. The bridge stamps trust_level="trusted" per thread
(createSessionConfig), which cannot be overridden from outside. Needs an
upstream issue / bridge characterization pass. The GatewayACPClient fs-write
gate covers any DELEGATED writes (_gate_delegated_fs_ask below), but current
codex applies patches locally.
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
from ..stream_consolidator import StreamConsolidator
from .provider_errors import parse_codex_provider_error

logger = logging.getLogger(__name__)


def _resolve_agent_mode(config: AgentSessionConfig) -> str:
    """Map session permission scopes to a codex-acp AgentMode preset.

    Any gated scope (DENY or ASK on EDIT/EXECUTE) selects "read-only" — the
    most restrictive preset the bridge exposes. See module docstring for the
    enforcement gap that remains even in this mode.
    """
    for kind in (ToolKind.EDIT, ToolKind.EXECUTE):
        if resolve_mode(config.permissions, kind) in (PermissionMode.DENY, PermissionMode.ASK):
            return "read-only"
    return "agent"


class CodexAdapter(ACPAgentAdapter):
    def _create_consolidator(self, session_id: str) -> StreamConsolidator:
        return StreamConsolidator(
            session_id,
            parse_agent_error=parse_codex_provider_error,
        )

    def _gate_delegated_fs_ask(self) -> bool:
        """If the bridge ever delegates an fs write without a preceding
        permission request, the gateway client must surface ASK itself."""
        return True

    def _prepare_launch(self, config: AgentSessionConfig) -> LaunchAdjustment:
        if is_trivial_config(config):
            return LaunchAdjustment()
        fp = config_fingerprint(self._agent_id, self._directory_scope, config)

        extra_env = {"INITIAL_AGENT_MODE": _resolve_agent_mode(config)}

        if config.system_prompt_extension:
            prompt_path = launch_config_path(self._agent_id, fp, ".prompt.md")
            prompt_path.write_text(config.system_prompt_extension, encoding="utf-8")
            extra_env["CODEX_CONFIG"] = json.dumps(
                {"model_instructions_file": str(prompt_path)}
            )

        logger.info("Codex launch config: mode=%s codex_config=%s",
                    extra_env["INITIAL_AGENT_MODE"], "CODEX_CONFIG" in extra_env)
        return LaunchAdjustment(extra_env=extra_env)
