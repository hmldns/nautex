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
from acp.schema import AllowedOutcome, DeniedOutcome

from ..protocol import (
    ConsolidatedSessionUpdate,
    PermissionRequestPayload,
    PermissionResponsePayload,
    PermissionAction,
    ToolKind,
)
from .stream_consolidator import StreamConsolidator

logger = logging.getLogger(__name__)


# Words in an option's option_id that hint it's a "continue-style" reject —
# the turn keeps iterating after denial (e.g. Codex exec offers "denied" =
# "No, continue without running it" vs "abort" = turn-cancel). Prefer these
# when multiple reject_once options exist.
_CONTINUE_REJECT_IDS = ("denied", "reject", "deny", "skip", "no_once")
# Outcome literal used for every non-cancel decision in ACP; option_id alone
# distinguishes approve vs deny.
_SELECTED = "selected"


def _pick_reject_option(options: list):
    """Choose the best reject option when we want to deny but continue the turn.

    Prefers option_ids suggesting "continue after no" (denied/reject/skip) over
    "abort" style rejects which agents tend to interpret as cancel-the-turn.
    Returns the PermissionOption or None if nothing reject-like is offered.
    """
    rejects = [o for o in options if o.kind and "reject" in str(o.kind)]
    for o in rejects:
        oid = str(getattr(o, "option_id", "")).lower()
        if any(w in oid for w in _CONTINUE_REJECT_IDS):
            return o
    return rejects[0] if rejects else None


def _pick_allow_option(options: list):
    """Choose the best allow option (allow_once preferred over allow_always)."""
    for kind in ("allow_once", "allow_always"):
        for o in options:
            if o.kind and kind in str(o.kind):
                return o
    return options[0] if options else None


def _map_response_to_acp(action: PermissionAction, options: list) -> "acp.RequestPermissionResponse":
    """Map our PermissionAction to an ACP RequestPermissionResponse.

    Rules:
    - APPROVE → pick an allow option; fall back to first option.
    - DENY    → pick a continue-style reject option; fall back to any reject;
                last-resort DeniedOutcome(cancelled), which cancels the turn.
    """
    if action == PermissionAction.APPROVE:
        opt = _pick_allow_option(options)
        if opt is not None:
            return acp.RequestPermissionResponse(
                outcome=AllowedOutcome(option_id=opt.option_id, outcome=_SELECTED)
            )
        # No options at all — nothing sensible to return; fall through to cancel.
    else:
        opt = _pick_reject_option(options)
        if opt is not None:
            return acp.RequestPermissionResponse(
                outcome=AllowedOutcome(option_id=opt.option_id, outcome=_SELECTED)
            )
    # Last resort: turn-cancel. Agents may interpret this as aborting the prompt.
    return acp.RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))


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
        response_mapper=None,
    ):
        self._acp_session_id = acp_session_id
        self._consolidator = consolidator
        self._on_update = on_update
        self._on_permission_request = on_permission_request
        self._cwd = os.path.abspath(cwd)
        self._terminals: dict = {}
        # Per-adapter override for mapping our PermissionAction → ACP response.
        # Default is the spec-correct mapper (pick reject_once option on deny,
        # fall back to DeniedOutcome which cancels the turn).
        self._response_mapper = response_mapper or _map_response_to_acp

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
        tool_call_id = getattr(tool_call, "tool_call_id", None) if tool_call else None

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
            tool_call_id=tool_call_id,
            path=path,
            command=command,
        )

        opts_debug = [(getattr(o, "option_id", "?"), str(getattr(o, "kind", "?"))) for o in (options or [])]
        logger.info("Permission request: %s (kind=%s) options=%s", title, kind_str, opts_debug)

        # Delegate to callback (cloud UI or auto-approve)
        response = await self._on_permission_request(prp)

        # If the session policy auto-decided, surface the outcome on the tool
        # call widget so it doesn't sit visibly "Done" while actually denied.
        if prp.policy_action is not None and tool_call_id:
            await self._emit_policy_tool_update(tool_call_id, prp, response)

        opt_list = list(options or [])
        return self._response_mapper(response.action, opt_list)

    async def _emit_policy_tool_update(
        self,
        tool_call_id: str,
        prp: "PermissionRequestPayload",
        response: "PermissionResponsePayload",
    ) -> None:
        """Emit a synthetic tool_call_update so the UI reflects the policy outcome."""
        from ..protocol import ConsolidatedSessionUpdate, SessionUpdateKind, ToolCallStatus
        denied = response.action == PermissionAction.DENY
        csu = ConsolidatedSessionUpdate(
            kind=SessionUpdateKind.TOOL_CALL_UPDATE,
            acp_session_id=self._acp_session_id,
            tool_call_id=tool_call_id,
            tool_status=ToolCallStatus.ERROR if denied else ToolCallStatus.COMPLETED,
            text="Denied by policy" if denied else "Allowed by policy",
        )
        try:
            await self._on_update(csu)
        except Exception as e:
            logger.warning("Policy tool_call_update emit failed: %s", e)

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
