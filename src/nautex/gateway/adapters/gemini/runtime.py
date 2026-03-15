"""Gemini CLI — native ACP adapter runtime.

Gemini natively supports ACP over stdio via `gemini --experimental-acp`.
Capabilities: image blocks, embedded context. No dynamic port needed (stdio).

Reference: MDS-14, MDS-15
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


class GeminiAdapter(NativeACPAdapter):
    """Gemini CLI native ACP adapter.

    Launch: gemini --experimental-acp [--model MODEL] [-y] [--allowed-mcp-server-names ...]
    Transport: stdio
    """

    def __init__(self) -> None:
        self._state = AgentConnectionState.OFFLINE

    @property
    def manifest(self) -> AgentDescriptor:
        return AgentDescriptor(
            agent_id="gemini_cli",
            name="Gemini CLI",
            version="0.33.1",
            executable="gemini",
            agent_type="GEMINI_CLI",
            acp_supported=True,
            capabilities=AgentCapabilities(
                load_session=True,
                prompt_capabilities=PromptCapabilities(
                    image=True,
                    audio=True,
                    embedded_context=True,
                ),
            ),
            supported_models=[
                ModelInfo(id="gemini-2.5-pro", name="Gemini 2.5 Pro", provider="google", default=True),
                ModelInfo(id="gemini-2.5-flash", name="Gemini 2.5 Flash", provider="google"),
                ModelInfo(id="gemini-2.0-flash", name="Gemini 2.0 Flash", provider="google"),
            ],
        )

    @property
    def state(self) -> AgentConnectionState:
        return self._state

    def _build_launch_command(self, config: AgentConfig) -> List[str]:
        cmd = [self.manifest.executable, "--acp"]

        if config.model:
            cmd.extend(["--model", config.model])

        if config.permissions.auto_approve_all:
            cmd.append("-y")

        if config.mcp_servers:
            server_names = ",".join(s.server_id for s in config.mcp_servers)
            cmd.extend(["--allowed-mcp-server-names", server_names])

        return cmd

    # --- Lifecycle stubs (will be wired to process_manager in orchestration phase) ---

    async def connect(
        self,
        config: AgentConfig,
        on_system_event: Callable[[ConsolidatedSessionUpdate], Awaitable[None]],
    ) -> None:
        self._state = AgentConnectionState.INITIALIZING
        # TODO: wire to process_manager.spawn_process + stderr drain
        self._state = AgentConnectionState.ACTIVE

    async def create_session(self, config: GatewaySessionConfig) -> str:
        raise NotImplementedError("Session management deferred to orchestration phase")

    async def resume_session(self, session_id: str) -> None:
        raise NotImplementedError("Session management deferred to orchestration phase")

    async def submit_prompt_optimistic(
        self,
        session_id: str,
        content: PromptContent,
        on_update: Callable[[ConsolidatedSessionUpdate], Awaitable[None]],
        on_permission_request: Callable[
            [PermissionRequestPayload], Awaitable[PermissionResponsePayload]
        ],
    ) -> str:
        raise NotImplementedError("Prompt execution deferred to orchestration phase")

    async def execute_prompt_strict(
        self,
        session_id: str,
        content: PromptContent,
        on_update: Callable[[ConsolidatedSessionUpdate], Awaitable[None]],
        on_permission_request: Callable[
            [PermissionRequestPayload], Awaitable[PermissionResponsePayload]
        ],
    ) -> PromptResponse:
        raise NotImplementedError("Prompt execution deferred to orchestration phase")

    def get_telemetry(self) -> Dict[str, Any]:
        return {}

    async def cancel(self, session_id: str) -> None:
        raise NotImplementedError("Cancel deferred to orchestration phase")

    async def disconnect(self) -> None:
        # TODO: wire to process_manager.terminate_process
        self._state = AgentConnectionState.STOPPED
