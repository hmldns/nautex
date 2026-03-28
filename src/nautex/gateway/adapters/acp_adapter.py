"""Common ACP adapter — concrete implementation of AgentAdapter.

Drives any ACP-compatible agent via the agent-client-protocol SDK.
Per-agent subclasses can override auth, permission mapping, etc.

Reference: MDS-13, MDS-61
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

import acp
from acp import spawn_agent_process, text_block

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
from .base import AgentAdapter, AgentConnectionState
from .acp_client import GatewayACPClient
from .stream_consolidator import StreamConsolidator

logger = logging.getLogger(__name__)


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
        self._conn: Optional[Any] = None
        self._proc: Optional[Any] = None
        self._context_manager: Optional[Any] = None
        self._acp_session_id: Optional[str] = None
        self._consolidator: Optional[StreamConsolidator] = None
        self._on_system_event: Optional[Callable] = None
        self._available_models: List[str] = []
        self._current_model: str = ""

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

    async def connect(
        self,
        config: AgentSessionConfig,
        on_system_event: Callable[[ConsolidatedSessionUpdate], Awaitable[None]],
    ) -> None:
        """Spawn agent, initialize ACP, authenticate (skip on failure), create session."""
        self._on_system_event = on_system_event
        self._state = AgentConnectionState.INITIALIZING

        cmd = self._registration.executable
        args = self._registration.launch_args

        logger.info("Connecting adapter: %s (cmd=%s %s)", self._agent_id, cmd, " ".join(args))

        # Create client with mutable callback refs — rewired per-prompt
        self._client = GatewayACPClient(
            acp_session_id="",
            consolidator=StreamConsolidator(""),
            on_update=on_system_event,
            on_permission_request=self._noop_permission,
            cwd=self._directory_scope,
        )
        client = self._client

        # Spawn using ACP SDK
        self._context_manager = spawn_agent_process(
            client, cmd, *args, cwd=self._directory_scope,
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

        # Create session
        session = await self._conn.new_session(cwd=self._directory_scope, mcp_servers=[])
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
        session = await self._conn.new_session(cwd=self._directory_scope, mcp_servers=[])
        self._acp_session_id = session.session_id
        return self._acp_session_id

    async def load_session(self, acp_session_id: str) -> None:
        """Load existing ACP session — agent restores its own persisted history."""
        if not self._conn:
            raise RuntimeError("Adapter not connected")
        response = await self._conn.load_session(
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
        logger.info("ACP session loaded: %s (agent=%s)", acp_session_id, self._agent_id)

    async def resume_session(self, session_id: str) -> None:
        """Base class abstract method — delegates to load_session."""
        await self.load_session(session_id)

    async def set_model(self, model_id: str) -> bool:
        """Switch model mid-session via ACP set_session_model. Returns True on success."""
        if not self._conn or not self._acp_session_id:
            logger.warning("Cannot set model — no active connection/session for %s", self._agent_id)
            return False
        try:
            await self._conn.set_session_model(model_id=model_id, session_id=self._acp_session_id)
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

        acp_sid = self._acp_session_id
        consolidator = StreamConsolidator(acp_sid)
        self._consolidator = consolidator

        # Rewire the client's callbacks for this prompt
        self._client._consolidator = consolidator
        self._client._on_update = on_update
        self._client._on_permission_request = on_permission_request
        self._client._acp_session_id = acp_sid

        # Extract prompt text
        prompt_text = content.text

        logger.info("Prompting agent %s (session=%s): %s", self._agent_id, acp_sid, prompt_text[:80])

        try:
            result = await self._conn.prompt(
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
        """Cancel ongoing execution — kill the process."""
        if self._proc and self._proc.returncode is None:
            self._proc.kill()
            logger.info("Cancelled agent %s", self._agent_id)

    async def disconnect(self) -> None:
        """Teardown agent process."""
        if self._context_manager:
            try:
                await self._context_manager.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("Disconnect error for %s: %s", self._agent_id, e)
        self._state = AgentConnectionState.STOPPED
        self._conn = None
        self._proc = None
        logger.info("Adapter disconnected: %s", self._agent_id)

    @staticmethod
    async def _noop_permission(prp: PermissionRequestPayload) -> PermissionResponsePayload:
        """Default permission handler during connect — auto-approve."""
        from ..protocol import PermissionAction
        return PermissionResponsePayload(
            permission_id=prp.permission_id,
            acp_session_id=prp.acp_session_id,
            action=PermissionAction.APPROVE,
        )
