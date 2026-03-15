"""OpenCode — native ACP adapter runtime.

OpenCode supports ACP natively over HTTP with dynamic port assignment.
Launch: opencode acp --port 0 --cwd <directory_scope>
Uses port_discovery to detect the ephemeral port from stdout.

Reference: MDS-16, MDS-17
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


class OpenCodeAdapter(NativeACPAdapter):
    """OpenCode native ACP adapter with dynamic HTTP port.

    Launch: opencode acp --port 0 --cwd <dir>
    Transport: HTTP (port discovered from stdout)
    """

    def __init__(self) -> None:
        self._state = AgentConnectionState.OFFLINE

    @property
    def manifest(self) -> AgentDescriptor:
        return AgentDescriptor(
            agent_id="opencode",
            name="OpenCode",
            version="1.2.x",
            executable="opencode",
            agent_type="OPENCODE",
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
                ModelInfo(id="gemini-2.5-pro", name="Gemini 2.5 Pro", provider="google"),
            ],
        )

    @property
    def state(self) -> AgentConnectionState:
        return self._state

    def _build_launch_command(self, config: AgentConfig) -> List[str]:
        return [self.manifest.executable, "acp", "--port", "0", "--cwd", config.directory_scope]

    async def connect(
        self,
        config: AgentConfig,
        on_system_event: Callable[[ConsolidatedSessionUpdate], Awaitable[None]],
    ) -> None:
        self._state = AgentConnectionState.INITIALIZING
        # TODO: spawn_process + discover_dynamic_port + stderr drain
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
