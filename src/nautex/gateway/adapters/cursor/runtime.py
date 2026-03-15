"""Cursor Agent — external wrapper ACP adapter runtime.

Uses cursor-agent CLI binary to tunnel Cursor reasoning engine through stdio.

Reference: MDS-57, MDS-58
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List

from ...models import (
    AgentCapabilities,
    AgentConfig,
    AgentDescriptor,
    ConsolidatedSessionUpdate,
    GatewaySessionConfig,
    ModelInfo,
    PermissionRequestPayload,
    PermissionResponsePayload,
    PromptCapabilities,
    PromptContent,
    PromptResponse,
)
from ..base import AgentConnectionState, ExternalAdapterAgent


class CursorAdapter(ExternalAdapterAgent):
    """Cursor Agent external wrapper adapter.

    Launch: cursor-agent acp [--plan]
    Transport: stdio (via wrapper binary)
    """

    def __init__(self) -> None:
        self._state = AgentConnectionState.OFFLINE

    @property
    def manifest(self) -> AgentDescriptor:
        return AgentDescriptor(
            agent_id="cursor_agent",
            name="Cursor Agent",
            version="latest",
            executable="cursor-agent",
            agent_type="CURSOR_AGENT",
            acp_supported=True,
            capabilities=AgentCapabilities(
                load_session=True,
                prompt_capabilities=PromptCapabilities(
                    image=True,
                    audio=False,
                    embedded_context=False,
                ),
            ),
            supported_models=[
                ModelInfo(id="claude-sonnet-4-5", name="Claude Sonnet 4.5", provider="anthropic", default=True),
                ModelInfo(id="gpt-4.1", name="GPT-4.1", provider="openai"),
                ModelInfo(id="gemini-2.5-pro", name="Gemini 2.5 Pro", provider="google"),
            ],
        )

    @property
    def state(self) -> AgentConnectionState:
        return self._state

    def _build_launch_command(self, config: AgentConfig) -> List[str]:
        cmd = [self.manifest.executable, "acp"]
        if config.permissions.read_only:
            cmd.append("--plan")
        return cmd

    async def connect(
        self, config: AgentConfig,
        on_system_event: Callable[[ConsolidatedSessionUpdate], Awaitable[None]],
    ) -> None:
        self._state = AgentConnectionState.INITIALIZING
        self._state = AgentConnectionState.ACTIVE

    async def create_session(self, config: GatewaySessionConfig) -> str:
        raise NotImplementedError

    async def resume_session(self, session_id: str) -> None:
        raise NotImplementedError

    async def submit_prompt_optimistic(
        self, session_id: str, content: PromptContent,
        on_update: Callable[[ConsolidatedSessionUpdate], Awaitable[None]],
        on_permission_request: Callable[[PermissionRequestPayload], Awaitable[PermissionResponsePayload]],
    ) -> str:
        raise NotImplementedError

    async def execute_prompt_strict(
        self, session_id: str, content: PromptContent,
        on_update: Callable[[ConsolidatedSessionUpdate], Awaitable[None]],
        on_permission_request: Callable[[PermissionRequestPayload], Awaitable[PermissionResponsePayload]],
    ) -> PromptResponse:
        raise NotImplementedError

    def get_telemetry(self) -> Dict[str, Any]:
        return {}

    async def cancel(self, session_id: str) -> None:
        raise NotImplementedError

    async def disconnect(self) -> None:
        self._state = AgentConnectionState.STOPPED
