"""Factory Droid — custom HTTP adapter runtime.

Droid runs as an HTTP daemon with dynamic port binding.
Uses a custom HTTP API (no ACP on wire) — this adapter translates
those HTTP calls into ConsolidatedSessionUpdate objects.

Reference: MDS-18, MDS-19
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
from ..base import AgentConnectionState, CustomAdapterAgent


class DroidAdapter(CustomAdapterAgent):
    """Factory Droid custom HTTP adapter.

    Launch: droid daemon --port 0 --cwd <dir> [--model MODEL] [--auto low|high]
    Transport: HTTP (port discovered from stdout)
    """

    def __init__(self) -> None:
        self._state = AgentConnectionState.OFFLINE

    @property
    def manifest(self) -> AgentDescriptor:
        return AgentDescriptor(
            agent_id="droid",
            name="Factory Droid",
            version="latest",
            executable="droid",
            agent_type="DROID",
            acp_supported=False,
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
                ModelInfo(id="claude-opus-4", name="Claude Opus 4", provider="anthropic"),
            ],
        )

    @property
    def state(self) -> AgentConnectionState:
        return self._state

    def _build_launch_command(self, config: AgentConfig) -> List[str]:
        cmd = [self.manifest.executable, "daemon", "--port", "0", "--cwd", config.directory_scope]

        if config.model:
            cmd.extend(["--model", config.model])

        if config.tools_allowed:
            cmd.extend(["--enabled-tools", ",".join(config.tools_allowed)])

        if config.tools_denied:
            cmd.extend(["--disabled-tools", ",".join(config.tools_denied)])

        if config.permissions.read_only:
            cmd.extend(["--auto", "low"])
        else:
            cmd.extend(["--auto", "high"])

        return cmd

    async def connect(
        self, config: AgentConfig,
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
