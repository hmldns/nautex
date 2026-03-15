"""Goose — native ACP adapter runtime.

Goose supports ACP natively over stdio via `goose acp`.
Model override via GOOSE_MODEL env var.

Reference: MDS-59, MDS-65
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


class GooseAdapter(NativeACPAdapter):
    """Goose native ACP adapter.

    Launch: goose acp
    Transport: stdio
    Model override: GOOSE_MODEL env var
    """

    def __init__(self) -> None:
        self._state = AgentConnectionState.OFFLINE

    @property
    def manifest(self) -> AgentDescriptor:
        return AgentDescriptor(
            agent_id="goose",
            name="Goose",
            version="latest",
            executable="goose",
            agent_type="GOOSE",
            acp_supported=True,
            capabilities=AgentCapabilities(
                load_session=True,
                prompt_capabilities=PromptCapabilities(
                    image=True,
                    audio=False,
                    embedded_context=True,
                ),
            ),
            supported_models=[
                ModelInfo(id="claude-sonnet-4-5", name="Claude Sonnet 4.5", provider="anthropic", default=True),
                ModelInfo(id="claude-opus-4", name="Claude Opus 4", provider="anthropic"),
                ModelInfo(id="gpt-4.1", name="GPT-4.1", provider="openai"),
            ],
        )

    @property
    def state(self) -> AgentConnectionState:
        return self._state

    def _build_launch_command(self, config: AgentConfig) -> List[str]:
        return [self.manifest.executable, "acp"]

    def _build_env(self, config: AgentConfig) -> Dict[str, str]:
        env = super()._build_env(config)
        if config.model:
            env["GOOSE_MODEL"] = config.model
        return env

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
