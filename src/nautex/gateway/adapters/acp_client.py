"""ACP client for gateway context — handles fs, terminal, permissions, session updates.

Unlike ProbeClient (which auto-approves and prints), this client:
- Routes permission requests via callback (cloud UI or TUI approval)
- Feeds raw session updates into StreamConsolidator → CSU callbacks
- Executes fs/terminal operations locally (agent runs on gateway host)

Reference: MDS-13, MDSNAUTX-15
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Awaitable, Callable, List, Optional

import acp
from acp.schema import AllowedOutcome

from ..protocol import (
    ConsolidatedSessionUpdate,
    PermissionRequestPayload,
    PermissionResponsePayload,
    PermissionAction,
    ToolKind,
)
from .stream_consolidator import StreamConsolidator

logger = logging.getLogger(__name__)


class GatewayACPClient(acp.Client):
    """ACP server-side client for the gateway node.

    Implements the ACP contract that agents call into:
    fs operations, terminal, permission gating, session updates.
    """

    def __init__(
        self,
        acp_session_id: str,
        consolidator: StreamConsolidator,
        on_update: Callable[[ConsolidatedSessionUpdate], Awaitable[None]],
        on_permission_request: Callable[
            [PermissionRequestPayload], Awaitable[PermissionResponsePayload]
        ],
        cwd: str = ".",
    ):
        self._acp_session_id = acp_session_id
        self._consolidator = consolidator
        self._on_update = on_update
        self._on_permission_request = on_permission_request
        self._cwd = os.path.abspath(cwd)
        self._terminals: dict = {}

    # --- Filesystem (local execution) ---

    async def read_text_file(self, path, session_id=None, **kw):
        full = os.path.join(self._cwd, path) if not os.path.isabs(path) else path
        try:
            with open(full, "r") as f:
                return acp.ReadTextFileResponse(text=f.read())
        except Exception as e:
            return acp.ReadTextFileResponse(text=f"Error: {e}")

    async def write_text_file(self, path, text, session_id=None, **kw):
        full = os.path.join(self._cwd, path) if not os.path.isabs(path) else path
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)
        logger.debug("Wrote %d bytes to %s", len(text), full)
        return acp.WriteTextFileResponse()

    # --- Terminal (local execution) ---

    async def create_terminal(self, command, session_id=None, **kw):
        tid = f"term-{uuid.uuid4().hex[:8]}"
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=self._cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._terminals[tid] = proc
        logger.debug("Terminal %s: %s (pid=%d)", tid, command, proc.pid)
        return acp.CreateTerminalResponse(terminal_id=tid)

    async def terminal_output(self, session_id, terminal_id, **kw):
        proc = self._terminals.get(terminal_id)
        if not proc or not proc.stdout:
            return acp.TerminalOutputResponse(output="", isComplete=True)
        try:
            data = await asyncio.wait_for(proc.stdout.read(8192), timeout=10.0)
            return acp.TerminalOutputResponse(
                output=data.decode("utf-8", errors="replace"), truncated=False,
            )
        except asyncio.TimeoutError:
            return acp.TerminalOutputResponse(output="", truncated=False)

    async def wait_for_terminal_exit(self, session_id, terminal_id, **kw):
        proc = self._terminals.get(terminal_id)
        if not proc:
            return acp.WaitForTerminalExitResponse(exitCode=1)
        try:
            code = await asyncio.wait_for(proc.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            proc.kill()
            code = -1
        return acp.WaitForTerminalExitResponse(exitCode=code or 0)

    async def kill_terminal(self, session_id, terminal_id, **kw):
        proc = self._terminals.pop(terminal_id, None)
        if proc and proc.returncode is None:
            proc.kill()
        return acp.KillTerminalCommandResponse()

    async def release_terminal(self, session_id, terminal_id, **kw):
        self._terminals.pop(terminal_id, None)
        return acp.ReleaseTerminalResponse()

    # --- Permission gating (via callback → cloud/TUI) ---

    async def request_permission(self, options, session_id, tool_call, **kw):
        title = getattr(tool_call, "title", "unknown") if tool_call else "unknown"
        kind_str = getattr(tool_call, "kind", "") if tool_call else ""

        # Map ACP kind to protocol ToolKind
        tool_kind = None
        if kind_str:
            try:
                tool_kind = ToolKind(kind_str)
            except ValueError:
                pass

        # Build protocol-level permission request
        path = None
        command = None
        if tool_call and getattr(tool_call, "content", None):
            for block in tool_call.content:
                actual = getattr(block, "actual_instance", block)
                if hasattr(actual, "path"):
                    path = actual.path
                if hasattr(actual, "command"):
                    command = actual.command

        prp = PermissionRequestPayload(
            permission_id=f"perm-{uuid.uuid4().hex[:8]}",
            acp_session_id=self._acp_session_id,
            tool_name=title,
            tool_kind=tool_kind,
            path=path,
            command=command,
        )

        logger.info("Permission request: %s (kind=%s)", title, kind_str)

        # Delegate to callback (cloud UI or auto-approve)
        response = await self._on_permission_request(prp)

        # Map protocol response back to ACP format
        if response.action == PermissionAction.APPROVE:
            # Find the right option_id (agent-specific)
            for opt in (options or []):
                if opt.kind and "allow_once" in str(opt.kind):
                    return acp.RequestPermissionResponse(
                        outcome=AllowedOutcome(option_id=opt.option_id, outcome="selected")
                    )
            # Fallback
            oid = options[0].option_id if options else "proceed_once"
            return acp.RequestPermissionResponse(
                outcome=AllowedOutcome(option_id=oid, outcome="selected")
            )
        else:
            # Denied — use denied outcome
            return acp.RequestPermissionResponse(
                outcome=AllowedOutcome(option_id="denied", outcome="denied")
            )

    # --- Session updates (feed to StreamConsolidator → CSU callbacks) ---

    async def session_update(self, session_id, update, **kw):
        logger.info("session_update called: session=%s update_type=%s", session_id, getattr(update, 'session_update', '?'))
        if not update:
            return

        csus = self._consolidator.process(update)
        for csu in csus:
            await self._on_update(csu)

    # --- Extension methods ---

    async def ext_method(self, method, params):
        logger.debug("ext_method: %s", method)
        return {}

    async def ext_notification(self, method, params):
        pass

    def on_connect(self, conn):
        pass
