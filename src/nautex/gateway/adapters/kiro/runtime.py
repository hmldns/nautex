"""Kiro CLI — native ACP adapter runtime.

Kiro supports ACP natively over stdio via `kiro-cli acp`.
Directory scope injected via --directory flag.

Reference: MDS-74, MDS-75
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
from ..base import AgentConnectionState, NativeACPAdapter


class KiroAdapter(NativeACPAdapter):
    """Kiro CLI native ACP adapter.

    Launch: kiro-cli acp [--directory <dir>]
    Transport: stdio
    """

    def __init__(self) -> None:
        self._state = AgentConnectionState.OFFLINE

    @property
    def manifest(self) -> AgentDescriptor:
        return AgentDescriptor(
            agent_id="kiro_cli",
            name="Kiro CLI",
            version="latest",
            executable="kiro-cli",
            agent_type="KIRO_CLI",
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
                ModelInfo(id="claude-sonnet-4-5", name="Claude Sonnet 4.5", provider="anthropic", default=True),
            ],
        )

    @property
    def state(self) -> AgentConnectionState:
        return self._state

    def _build_launch_command(self, config: AgentConfig) -> List[str]:
        cmd = [self.manifest.executable, "acp"]
        if config.directory_scope:
            cmd.extend(["--directory", config.directory_scope])
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
