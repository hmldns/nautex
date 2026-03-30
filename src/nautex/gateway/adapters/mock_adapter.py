"""Mock testing agent — built-in adapter for uplink resilience testing.

Emits synthetic ConsolidatedSessionUpdate chunks at a configurable rate
without requiring an external AI binary. Used for closed-loop testing
of buffering, reconnection, and session recovery flows.

Reference: PRD-128
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

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
from ..protocol.enums import SessionUpdateKind
from .base import AgentAdapter, AgentConnectionState

logger = logging.getLogger(__name__)

MOCK_AGENT_ID = "mock_testing_agent"
DEFAULT_EMIT_INTERVAL = 3.0
MIN_EMIT_INTERVAL = 1.0


class MockTestingAgent(AgentAdapter):
    """Built-in mock agent that emits synthetic session updates.

    No external binary required. Starts a background loop that emits
    agent_message_chunk CSUs at a configurable rate (default 3s).
    First message is emitted immediately on connect.
    """

    def __init__(self) -> None:
        self._state = AgentConnectionState.OFFLINE
        self._acp_session_id: Optional[str] = None
        self._proc = None  # No OS process — satisfies _monitor_agent_process check
        self._emit_task: Optional[asyncio.Task] = None
        self._on_system_event: Optional[Callable[[ConsolidatedSessionUpdate], Awaitable[None]]] = None
        self._chunk_counter = 0
        self._emit_interval = DEFAULT_EMIT_INTERVAL

    @property
    def descriptor(self) -> AgentDescriptor:
        return AgentDescriptor(
            agent_id=MOCK_AGENT_ID,
            name="Mock Testing Agent",
            version="1.0.0",
        )

    @property
    def registration(self) -> SupportedAgentRegistration:
        return SupportedAgentRegistration(
            agent_id=MOCK_AGENT_ID,
            executable="<built-in>",
        )

    @property
    def state(self) -> AgentConnectionState:
        return self._state

    @property
    def pid(self) -> int:
        return 0

    @property
    def current_model(self) -> str:
        return "mock-v1"

    @property
    def available_models(self) -> list:
        return ["mock-v1"]

    def set_interval(self, seconds: float) -> None:
        """Change the emit interval. Minimum 1s."""
        self._emit_interval = max(seconds, MIN_EMIT_INTERVAL)
        logger.info("Mock emit interval set to %.1fs", self._emit_interval)

    async def connect(
        self,
        config: AgentSessionConfig,
        on_system_event: Callable[[ConsolidatedSessionUpdate], Awaitable[None]],
    ) -> None:
        self._on_system_event = on_system_event
        self._acp_session_id = f"mock-{uuid.uuid4().hex[:8]}"
        self._state = AgentConnectionState.ACTIVE
        self._emit_task = asyncio.create_task(self._emit_loop())
        logger.info("Mock agent connected: session=%s interval=%.1fs", self._acp_session_id, self._emit_interval)

    async def create_session(self, config: GatewaySessionConfig) -> str:
        return self._acp_session_id or ""

    async def load_session(self, acp_session_id: str) -> None:
        self._acp_session_id = acp_session_id
        logger.info("Mock agent loaded session: %s", acp_session_id)

    async def resume_session(self, session_id: str) -> None:
        self._acp_session_id = session_id
        self._state = AgentConnectionState.ACTIVE
        if not self._emit_task or self._emit_task.done():
            self._emit_task = asyncio.create_task(self._emit_loop())
        logger.info("Mock agent resumed: session=%s", session_id)

    async def prompt(
        self,
        session_id: str,
        content: PromptContent,
        on_update: Callable[[ConsolidatedSessionUpdate], Awaitable[None]],
        on_permission_request: Callable[
            [PermissionRequestPayload], Awaitable[PermissionResponsePayload]
        ],
    ) -> PromptResponse:
        text = content.text.strip()

        # /interval N — change emit period
        if text.startswith("/interval"):
            response_text = self._handle_interval_command(text)
        else:
            response_text = f"Echo: {text}"

        csu = ConsolidatedSessionUpdate(
            kind=SessionUpdateKind.AGENT_MESSAGE,
            session_id=session_id,
            acp_session_id=self._acp_session_id or "",
            text=response_text,
        )
        await on_update(csu)
        return PromptResponse(prompt_id=session_id, stop_reason="end_turn")

    def _handle_interval_command(self, text: str) -> str:
        """Parse '/interval N' and update emit rate."""
        parts = text.split()
        if len(parts) < 2:
            return f"Current interval: {self._emit_interval:.1f}s (min {MIN_EMIT_INTERVAL:.0f}s)"
        try:
            seconds = float(parts[1])
            self.set_interval(seconds)
            return f"Emit interval set to {self._emit_interval:.1f}s"
        except ValueError:
            return f"Usage: /interval <seconds> (min {MIN_EMIT_INTERVAL:.0f}s)"

    def get_telemetry(self) -> Dict[str, Any]:
        return {
            "agent_id": MOCK_AGENT_ID,
            "is_typing": self._state == AgentConnectionState.ACTIVE,
            "processed_tokens_estimate": self._chunk_counter * 10,
        }

    async def cancel(self, session_id: str) -> None:
        pass

    async def disconnect(self) -> None:
        self._state = AgentConnectionState.STOPPED
        if self._emit_task and not self._emit_task.done():
            self._emit_task.cancel()
            try:
                await self._emit_task
            except asyncio.CancelledError:
                pass
        logger.info("Mock agent disconnected")

    async def _emit_loop(self) -> None:
        """Emit first message immediately, then at configured interval."""
        first = True
        while self._state == AgentConnectionState.ACTIVE:
            if first:
                first = False
            else:
                await asyncio.sleep(self._emit_interval)
            if self._on_system_event and self._acp_session_id:
                self._chunk_counter += 1
                csu = ConsolidatedSessionUpdate(
                    kind=SessionUpdateKind.AGENT_MESSAGE,
                    acp_session_id=self._acp_session_id,
                    text=f"[mock heartbeat #{self._chunk_counter}] ",
                )
                try:
                    await self._on_system_event(csu)
                except Exception as e:
                    logger.warning("Mock emit failed: %s", e)
