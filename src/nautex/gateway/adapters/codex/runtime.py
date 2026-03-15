"""Codex — external wrapper ACP adapter runtime.

Uses Zed's codex-acp wrapper to tunnel the agent through stdio.

Reference: MDS-66, MDS-68
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


class CodexAdapter(ExternalAdapterAgent):
    """Codex external wrapper adapter.

    Launch: codex-acp
    Transport: stdio (via wrapper binary)
    """

    def __init__(self) -> None:
        self._state = AgentConnectionState.OFFLINE

    @property
    def manifest(self) -> AgentDescriptor:
        return AgentDescriptor(
            agent_id="codex",
            name="Codex",
            version="latest",
            executable="codex-acp",
            agent_type="CODEX",
            acp_supported=True,
            capabilities=AgentCapabilities(
                load_session=True,
                prompt_capabilities=PromptCapabilities(
                    image=False,
                    audio=False,
                    embedded_context=True,
                ),
            ),
            supported_models=[
                ModelInfo(id="o3", name="o3", provider="openai", default=True),
                ModelInfo(id="o4-mini", name="o4-mini", provider="openai"),
            ],
        )

    @property
    def state(self) -> AgentConnectionState:
        return self._state

    def _build_launch_command(self, config: AgentConfig) -> List[str]:
        return [self.manifest.executable]

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
