"""Common ACP adapter — concrete implementation of AgentAdapter.

Drives any ACP-compatible agent via the agent-client-protocol SDK.
Per-agent subclasses can override auth, permission mapping, etc.

Reference: MDS-13, MDS-61
"""

from __future__ import annotations

import asyncio.subprocess
import logging
from contextlib import AbstractAsyncContextManager
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import acp
from acp import spawn_agent_process, text_block
from acp.client.connection import ClientSideConnection

from ..config import get_registration, build_launch_command, resolve_auth_method
from ..models import (
    AgentDescriptor,
    AgentSessionConfig,
    ConsolidatedSessionUpdate,
    GatewaySessionConfig,
    PermissionRequestPayload,
    PermissionResponsePayload,
    PromptContent,
    PromptResponse,
    SupportedAgentRegistration,
)
from ..protocol.enums import PermissionAction, PermissionMode, SessionUpdateKind
from .base import AgentAdapter, AgentConnectionState
from .acp_client import GatewayACPClient
from .launch_config import LaunchAdjustment, apply_implicit_permissions, resolve_mode
from .stream_consolidator import StreamConsolidator

logger = logging.getLogger(__name__)


class AdapterNotConnectedError(Exception):
    """Raised when an operation requires an active ACP connection that hasn't been established."""

    def __init__(self, agent_id: str, operation: str):
        super().__init__(f"Agent '{agent_id}' has no ACP connection — call connect() before {operation}()")


class AdapterNoSessionError(Exception):
    """Raised when an operation requires an ACP session that hasn't been created."""

    def __init__(self, agent_id: str, operation: str):
        super().__init__(f"Agent '{agent_id}' has no ACP session — call connect() or create_session() before {operation}()")


def create_adapter(agent_id: str, directory_scope: str) -> "ACPAgentAdapter":
    """Factory: pick the per-agent subclass for native config generation.

    Falls back to base ACPAgentAdapter for agents without a specialization
    (MCP injection via ACP new_session still works as a default path).
    """
    if agent_id == "opencode":
        from .opencode.runtime import OpenCodeAdapter
        return OpenCodeAdapter(agent_id, directory_scope)
    if agent_id == "claude_code":
        from .claude.runtime import ClaudeAdapter
        return ClaudeAdapter(agent_id, directory_scope)
    if agent_id == "codex":
        from .codex.runtime import CodexAdapter
        return CodexAdapter(agent_id, directory_scope)
    return ACPAgentAdapter(agent_id, directory_scope)


class ACPAgentAdapter(AgentAdapter):
    """Concrete ACP adapter — drives an agent via the ACP SDK.

    Lifecycle:
    1. connect() → spawn process, initialize, auth, create session
    2. prompt() → send prompt, stream CSUs via callback
    3. disconnect() → teardown process
    """

    def __init__(self, agent_id: str, directory_scope: str):
        self._agent_id = agent_id
        self._directory_scope = directory_scope
        self._registration = get_registration(agent_id)
        self._descriptor = AgentDescriptor(
            agent_id=agent_id,
            executable=self._registration.executable,
        )
        self._state = AgentConnectionState.OFFLINE
        self._conn: Optional[ClientSideConnection] = None
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._context_manager: Optional[
            AbstractAsyncContextManager[Tuple[ClientSideConnection, asyncio.subprocess.Process]]
        ] = None
        self._acp_session_id: Optional[str] = None
        self._consolidator: Optional[StreamConsolidator] = None
        self._on_system_event: Optional[Callable[[ConsolidatedSessionUpdate], Awaitable[None]]] = None
        self._available_models: List[str] = []
        self._current_model: str = ""
        self._is_restoring = False
        self._config: Optional[AgentSessionConfig] = None
        self._client: Optional[GatewayACPClient] = None
        self._launch_adjustment: Optional[LaunchAdjustment] = None
        self._system_prompt_sent: bool = False

    @property
    def restoring(self) -> bool:
        return self._is_restoring

    @property
    def descriptor(self) -> AgentDescriptor:
        return self._descriptor

    @property
    def pid(self) -> int:
        """PID of the agent subprocess, or 0 if not running."""
        return self._proc.pid if self._proc else 0

    @property
    def available_models(self) -> List[str]:
        return self._available_models

    @property
    def current_model(self) -> str:
        return self._current_model

    @property
    def registration(self) -> SupportedAgentRegistration:
        return self._registration

    @property
    def state(self) -> AgentConnectionState:
        return self._state

    def _require_conn(self, operation: str) -> ClientSideConnection:
        """Return the active connection or raise AdapterNotConnectedError."""
        if self._conn is None:
            raise AdapterNotConnectedError(self._agent_id, operation)
        return self._conn

    def _require_session(self, operation: str) -> Tuple[ClientSideConnection, str]:
        """Return (connection, session_id) or raise if either is missing."""
        conn = self._require_conn(operation)
        if self._acp_session_id is None:
            raise AdapterNoSessionError(self._agent_id, operation)
        return conn, self._acp_session_id

    def _prepare_launch(self, config: AgentSessionConfig) -> LaunchAdjustment:
        """Generate agent-native config files and return launch adjustments.

        Base implementation is a no-op — subclasses override to emit
        opencode.json / settings.json / config.toml etc. and point the
        agent binary at them via env vars or CLI flags.
        """
        return LaunchAdjustment()

    def _permission_response_mapper(self):
        """Hook to customize PermissionAction → ACP response translation.

        Return a callable `(PermissionAction, options) -> RequestPermissionResponse`
        or None to use the spec-correct default (pick reject_once on deny,
        fall back to DeniedOutcome/cancelled). Override in per-agent adapters
        when the agent has quirks — e.g. Claude respects reject_once as a
        definitive user rejection and stops the turn silently.
        """
        return None


    @staticmethod
    def _build_acp_mcp_servers(config: AgentSessionConfig) -> list:
        """Transform MCPServerConfig list → ACP SDK McpServerStdio list."""
        if not config.mcp_servers:
            return []
        from acp.schema import McpServerStdio, EnvVariable
        return [
            McpServerStdio(
                name=m.server_id,
                command=m.command,
                args=m.args,
                env=[EnvVariable(name=k, value=v) for k, v in m.env.items()],
            )
            for m in config.mcp_servers
        ]

    async def connect(
        self,
        config: AgentSessionConfig,
        on_system_event: Callable[[ConsolidatedSessionUpdate], Awaitable[None]],
    ) -> None:
        """Spawn agent, initialize ACP, authenticate (skip on failure), create session."""
        # Apply pragmatic permission rule, then generate native config
        config = apply_implicit_permissions(config)
        self._config = config
        self._on_system_event = on_system_event
        self._state = AgentConnectionState.INITIALIZING

        adjustment = self._prepare_launch(config)
        self._launch_adjustment = adjustment

        cmd = self._registration.executable
        args = list(self._registration.launch_args) + list(adjustment.extra_args)
        spawn_env = None
        if adjustment.extra_env:
            import os
            spawn_env = {**os.environ, **adjustment.extra_env}

        logger.info("Connecting adapter: %s (cmd=%s %s)", self._agent_id, cmd, " ".join(args))

        # Create client with mutable callback refs — rewired per-prompt.
        # response_mapper is a per-adapter hook — subclasses override
        # `_permission_response_mapper()` to customize how we translate
        # PermissionAction → ACP RequestPermissionResponse for their agent.
        self._client = GatewayACPClient(
            acp_session_id="",
            consolidator=StreamConsolidator(""),
            on_update=on_system_event,
            on_permission_request=self._noop_permission,
            cwd=self._directory_scope,
            response_mapper=self._permission_response_mapper(),
        )
        client = self._client

        # Spawn using ACP SDK — large limit for agents that return file contents
        self._context_manager = spawn_agent_process(
            client, cmd, *args, cwd=self._directory_scope, env=spawn_env,
            transport_kwargs={"limit": 10 * 1024 * 1024},  # 10MB stdio buffer
        )
        self._conn, self._proc = await self._context_manager.__aenter__()

        # Initialize
        from acp.schema import ClientCapabilities, FileSystemCapabilities, Implementation
        init = await self._conn.initialize(
            protocol_version=acp.PROTOCOL_VERSION,
            client_capabilities=ClientCapabilities(
                fs=FileSystemCapabilities(read_text_file=True, write_text_file=True),
                terminal=True,
            ),
            client_info=Implementation(name="nautex-gateway", title="Nautex Gateway", version="1.0.0"),
        )

        # Update descriptor from init response
        agent_info = getattr(init, "agent_info", None)
        if agent_info:
            self._descriptor.name = getattr(agent_info, "name", self._agent_id)
            self._descriptor.version = getattr(agent_info, "version", "")

        # Authenticate (skip on failure — OpenCode, Kiro, Goose pattern)
        auth_methods = getattr(init, "auth_methods", []) or []
        if auth_methods:
            method = resolve_auth_method(self._registration, auth_methods)
            if method:
                try:
                    await self._conn.authenticate(method_id=method)
                    logger.info("Auth OK: %s", method)
                except Exception as e:
                    logger.info("Auth skipped for %s: %s", self._agent_id, e)

        # Create session — inject MCP servers from config
        acp_mcp_servers = self._build_acp_mcp_servers(config)
        session = await self._conn.new_session(cwd=self._directory_scope, mcp_servers=acp_mcp_servers)
        self._acp_session_id = session.session_id
        model_state = session.models
        if model_state:
            self._available_models = [m.model_id for m in model_state.available_models] if model_state.available_models else []
            self._current_model = model_state.current_model_id or ""
        logger.info("ACP session: %s (agent=%s) models=%d current=%s",
                     self._acp_session_id, self._agent_id, len(self._available_models), self._current_model)

        self._state = AgentConnectionState.ACTIVE

    async def create_session(self, config: GatewaySessionConfig) -> str:
        """Create a new ACP session. Returns acp_session_id."""
        conn = self._require_conn("create_session")
        if self._config is None:
            raise AdapterNotConnectedError(self._agent_id, "create_session")
        session = await conn.new_session(cwd=self._directory_scope, mcp_servers=self._build_acp_mcp_servers(self._config))
        self._acp_session_id = session.session_id
        return self._acp_session_id

    async def load_session(self, acp_session_id: str) -> None:
        """Load existing ACP session — agent restores its own persisted history.

        Sets _restoring=True to suppress replayed session updates.
        Cleared when prompt() is called (first real user interaction).
        """
        conn = self._require_conn("load_session")
        self._is_restoring = True
        response = await conn.load_session(
            cwd=self._directory_scope,
            session_id=acp_session_id,
            mcp_servers=[],
        )
        self._acp_session_id = acp_session_id
        model_state = response.models if response else None
        if model_state:
            self._available_models = [m.model_id for m in model_state.available_models] if model_state.available_models else []
            self._current_model = model_state.current_model_id or ""
        self._state = AgentConnectionState.ACTIVE
        logger.info("ACP session loaded: %s (agent=%s, restoring=suppressed)", acp_session_id, self._agent_id)

    async def resume_session(self, session_id: str) -> None:
        """Base class abstract method — delegates to load_session."""
        await self.load_session(session_id)

    async def set_model(self, model_id: str) -> bool:
        """Switch model mid-session via ACP set_session_model. Returns True on success."""
        try:
            conn, acp_sid = self._require_session("set_model")
            await conn.set_session_model(model_id=model_id, session_id=acp_sid)
            logger.info("Model set to %s for agent %s", model_id, self._agent_id)
            return True
        except Exception as e:
            logger.error("Failed to set model %s for %s: %s", model_id, self._agent_id, e)
            return False

    async def prompt(
        self,
        session_id: str,
        content: PromptContent,
        on_update: Callable[[ConsolidatedSessionUpdate], Awaitable[None]],
        on_permission_request: Callable[
            [PermissionRequestPayload], Awaitable[PermissionResponsePayload]
        ],
    ) -> PromptResponse:
        """Send prompt to agent and stream CSUs via on_update callback."""
        if self._state != AgentConnectionState.ACTIVE:
            raise RuntimeError(f"Adapter not active (state={self._state})")
        conn, acp_sid = self._require_session("prompt")
        if self._client is None:
            raise AdapterNotConnectedError(self._agent_id, "prompt")
        self._is_restoring = False

        consolidator = StreamConsolidator(acp_sid)
        self._consolidator = consolidator

        # Rewire the client's callbacks for this prompt
        self._client._consolidator = consolidator
        self._client._on_update = on_update
        self._client._on_permission_request = self._wrap_permission_callback(on_permission_request)
        self._client._acp_session_id = acp_sid

        # Extract prompt text. On the first prompt of a session, prepend the
        # session policy (system_prompt_extension) inline as plain prose so the
        # agent treats it as natural setup rather than a tagged directive
        # block (which smaller agents tend to ignore or over-interpret).
        prompt_text = content.text
        if not self._system_prompt_sent and self._config and self._config.system_prompt_extension:
            prompt_text = (
                f"{self._config.system_prompt_extension}\n\n"
                f"Initial request: {prompt_text}"
            )
            self._system_prompt_sent = True

        logger.info("Prompting agent %s (session=%s): %s", self._agent_id, acp_sid, prompt_text[:80])

        try:
            result = await conn.prompt(
                session_id=acp_sid,
                prompt=[text_block(prompt_text)],
            )

            # Flush any remaining buffered text
            remaining = consolidator.flush()
            for csu in remaining:
                await on_update(csu)

            logger.info("Prompt complete: %s (stop=%s)", acp_sid, getattr(result, "stop_reason", "?"))

            return PromptResponse(
                prompt_id=acp_sid,
                stop_reason=str(getattr(result, "stop_reason", "end_turn")),
            )
        except acp.exceptions.RequestError as e:
            # JSON-RPC error from the agent — structured (code, message, data).
            # The agent's actionable text (rate-limit, upgrade URL, retry-at)
            # typically lives in `data`; `str(e)` alone is generic.
            code = getattr(e, "code", -32603)
            data = getattr(e, "data", None)
            summary = self._format_error_data(data) or str(e)
            import json as _json
            try:
                detail_json = _json.dumps(data, indent=2) if data is not None else None
            except Exception:
                detail_json = repr(data)
            logger.error("Prompt failed for %s (code=%s data=%r): %s", self._agent_id, code, data, e)
            try:
                await on_update(ConsolidatedSessionUpdate(
                    kind=SessionUpdateKind.AGENT_ERROR,
                    acp_session_id=acp_sid,
                    text=summary,
                    error_code=code,
                    error_detail=detail_json,
                ))
            except Exception as emit_err:
                logger.warning("Failed to emit AGENT_ERROR CSU: %s", emit_err)
            # Request-level error — the process is still alive and the session
            # remains usable. Don't mark the adapter as CRASHED; the user can
            # retry the prompt once the underlying condition is resolved.
            return PromptResponse(prompt_id=acp_sid, stop_reason="refusal")
        except Exception as e:
            self._state = AgentConnectionState.CRASHED
            logger.error("Prompt failed for %s: %s", self._agent_id, e)
            raise

    def get_telemetry(self) -> Dict[str, Any]:
        if self._consolidator:
            tel = self._consolidator.get_telemetry()
            return tel.model_dump()
        return {}

    async def cancel(self, session_id: str) -> None:
        """Cancel the current turn via the native ACP `session/cancel` notification.

        Per TRD-86, we must avoid OS-level process kills (SIGTERM/SIGKILL) for
        turn interruption — the agent should unwind naturally and the in-flight
        `session/prompt` call is expected to resolve with `stop_reason="cancelled"`,
        which the prompt loop treats as TURN_COMPLETE. We therefore send the
        `session/cancel` notification through the live ACP connection when
        available and leave the agent process running.

        The `session_id` parameter from callers is the **backend** session id
        (used to find this adapter); the ACP protocol needs the **ACP** session
        id, which the adapter captured during `create_session`/`load_session`.
        We use the stored `_acp_session_id` for the notification.
        """
        conn = self._conn
        acp_sid = self._acp_session_id
        if conn is None or not acp_sid:
            logger.debug(
                "cancel: no active ACP session for %s (backend=%s, acp=%s)",
                self._agent_id, session_id, acp_sid,
            )
            return
        try:
            await conn.cancel(acp_sid)
            logger.info("ACP session/cancel sent: agent=%s acp_session=%s", self._agent_id, acp_sid)
        except Exception as e:
            logger.warning(
                "ACP session/cancel failed for %s (acp_session=%s): %s",
                self._agent_id, acp_sid, e,
            )

    async def disconnect(self) -> None:
        """Teardown agent process."""
        if self._context_manager:
            try:
                await self._context_manager.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("Disconnect error for %s: %s", self._agent_id, e)
        self._launch_adjustment = None
        self._state = AgentConnectionState.STOPPED
        self._conn = None
        self._proc = None
        logger.info("Adapter disconnected: %s", self._agent_id)

    @staticmethod
    def _format_error_data(data) -> str:
        """Render the JSON-RPC error.data payload as user-friendly text.

        Bridges often stash the native CLI's error message in `data` — e.g.
        Codex puts rate-limit text ("You've hit your usage limit...") here.
        We accept common shapes: str, dict with message-ish keys, list, or fallback
        to repr. Whatever we return goes straight into an agent_message chunk.
        """
        if data is None:
            return ""
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            for key in ("message", "detail", "description", "error", "text"):
                val = data.get(key)
                if isinstance(val, str) and val:
                    return val
            import json as _json
            try:
                return _json.dumps(data, indent=2)
            except Exception:
                return repr(data)
        return repr(data)

    @staticmethod
    async def _noop_permission(prp: PermissionRequestPayload) -> PermissionResponsePayload:
        """Default permission handler during connect — auto-approve."""
        from ..protocol import PermissionAction
        return PermissionResponsePayload(
            permission_id=prp.permission_id,
            acp_session_id=prp.acp_session_id,
            action=PermissionAction.APPROVE,
        )

    def _wrap_permission_callback(
        self,
        outer: Callable[[PermissionRequestPayload], Awaitable[PermissionResponsePayload]],
    ) -> Callable[[PermissionRequestPayload], Awaitable[PermissionResponsePayload]]:
        """Apply the session's permission map before the outer handler surfaces to UI.

        For DENY/ALLOW, the adapter stamps prp.policy_action with the forced
        outcome and still calls outer — so the backend records the permission
        item in its terminal state without waiting for user input. ASK forwards
        unchanged and the outer handler surfaces an interactive prompt.
        Unknown tool_kind → fail-closed DENY.
        """
        permissions = self._config.permissions if self._config else {}
        agent_id = self._agent_id

        async def _gated(prp: PermissionRequestPayload) -> PermissionResponsePayload:
            kind = prp.tool_kind
            if kind is None:
                # Unknown kind: don't decide for the user, let them see it.
                return await outer(prp)
            mode = resolve_mode(permissions, kind)
            if mode == PermissionMode.DENY:
                logger.info("[%s] Policy deny %s (kind=%s)", agent_id, prp.tool_name, kind.value)
                prp.policy_action = PermissionAction.DENY
                return await outer(prp)
            if mode == PermissionMode.ALLOW:
                logger.info("[%s] Policy allow %s (kind=%s)", agent_id, prp.tool_name, kind.value)
                prp.policy_action = PermissionAction.APPROVE
                return await outer(prp)
            # ASK and DEFAULT both surface to the user; only DENY/ALLOW pre-decide.
            return await outer(prp)

        return _gated
