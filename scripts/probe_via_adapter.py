#!/usr/bin/env python3
"""Probe using ACPAgentAdapter — validates the production adapter path.

Compares with probe_acp_agents.py to find gaps in the adapter layer.
"""

import asyncio
import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nautex.gateway.adapters.acp_adapter import ACPAgentAdapter
from nautex.gateway.models import AgentSessionConfig, PromptContent
from nautex.gateway.protocol import ConsolidatedSessionUpdate, PermissionRequestPayload, PermissionResponsePayload, PermissionAction

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("probe_adapter")


async def on_update(csu: ConsolidatedSessionUpdate) -> None:
    logger.info("CSU: kind=%s acp_session_id=%s text=%s", csu.kind, csu.acp_session_id, (csu.text or "")[:80])


async def on_permission(prp: PermissionRequestPayload) -> PermissionResponsePayload:
    logger.info("PERMISSION: %s (auto-approve)", prp.tool_name)
    return PermissionResponsePayload(
        permission_id=prp.permission_id,
        acp_session_id=prp.acp_session_id,
        action=PermissionAction.APPROVE,
    )


async def main():
    agent_id = sys.argv[1] if len(sys.argv) > 1 else "opencode"
    prompt_text = sys.argv[2] if len(sys.argv) > 2 else "Say hello. One word only."

    with tempfile.TemporaryDirectory(prefix=f"nautex-adapter-probe-{agent_id}-") as tmpdir:
        logger.info("Agent: %s, Workspace: %s", agent_id, tmpdir)

        adapter = ACPAgentAdapter(agent_id, tmpdir)

        logger.info("--- Connect ---")
        await adapter.connect(
            config=AgentSessionConfig(directory_scope=tmpdir),
            on_system_event=on_update,
        )
        logger.info("Connected: state=%s session=%s", adapter.state, adapter._acp_session_id)

        logger.info("--- Prompt ---")
        result = await adapter.prompt(
            session_id=adapter._acp_session_id,
            content=PromptContent(text=prompt_text),
            on_update=on_update,
            on_permission_request=on_permission,
        )
        logger.info("--- Done: stop_reason=%s ---", result.stop_reason)

        await adapter.disconnect()
        logger.info("Disconnected")


if __name__ == "__main__":
    asyncio.run(main())
