"""Agent adapter abstract interfaces and class hierarchy.

Defines the normalization boundary between Nautex and third-party agent
binaries. Concrete adapters implement these interfaces to manage OS process
lifecycle and normalize native communication streams into standard domain objects.

Class hierarchy (MDS-61):
    AgentAdapter (ABC)
    ├── NativeACPAdapter      — agent speaks ACP directly (stdio transport)
    ├── ExternalAdapterAgent  — spawns wrapper binary that translates native → ACP
    └── CustomAdapterAgent    — custom agent-specific API (no ACP on wire)

Reference: MDS-13, MDS-61
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List

from ..models import (
    AgentConfig,
    AgentDescriptor,
    ConsolidatedSessionUpdate,
    GatewaySessionConfig,
    PermissionRequestPayload,
    PermissionResponsePayload,
    PromptContent,
    PromptResponse,
)


class AgentConnectionState(str, Enum):
    """Lifecycle state of an agent adapter's OS process.

    Reference: MDS-5
    """
    OFFLINE = "offline"
    INITIALIZING = "initializing"
    ACTIVE = "active"
    CRASHED = "crashed"
    STOPPED = "stopped"


class AgentAdapter(ABC):
    """Abstract adapter for managing a third-party agent's OS lifecycle
    and normalizing its communication streams into semantic chunks.

    Reference: MDS-13
    """

    @property
    @abstractmethod
    def manifest(self) -> "AgentDescriptor":
        """Static descriptor with agent metadata and capabilities."""
        ...

    @property
    @abstractmethod
    def state(self) -> AgentConnectionState:
        """Current lifecycle state of the adapter."""
        ...

    @abstractmethod
    async def connect(
        self,
        config: "AgentConfig",
        on_system_event: Callable[["ConsolidatedSessionUpdate"], Awaitable[None]],
    ) -> None:
        """Initialize the agent process and establish the async notification pipe.

        Spawns the OS subprocess, performs port discovery if needed, and starts
        the stderr drain daemon. The on_system_event callback receives out-of-band
        events (stderr batches, idle crashes) for the lifetime of the connection.
        """
        ...

    @abstractmethod
    async def create_session(self, config: "GatewaySessionConfig") -> str:
        """Create a new agent session. Returns session ID."""
        ...

    @abstractmethod
    async def resume_session(self, session_id: str) -> None:
        """Invoke session/load for state reconciliation.

        The agent replays its history via update notifications.
        """
        ...

    @abstractmethod
    async def submit_prompt_optimistic(
        self,
        session_id: str,
        content: "PromptContent",
        on_update: Callable[["ConsolidatedSessionUpdate"], Awaitable[None]],
        on_permission_request: Callable[
            ["PermissionRequestPayload"], Awaitable["PermissionResponsePayload"]
        ],
    ) -> str:
        """Stream-based prompt execution. Returns prompt ID."""
        ...

    @abstractmethod
    async def execute_prompt_strict(
        self,
        session_id: str,
        content: "PromptContent",
        on_update: Callable[["ConsolidatedSessionUpdate"], Awaitable[None]],
        on_permission_request: Callable[
            ["PermissionRequestPayload"], Awaitable["PermissionResponsePayload"]
        ],
    ) -> "PromptResponse":
        """Blocking prompt execution. Returns full response."""
        ...

    @abstractmethod
    def get_telemetry(self) -> Dict[str, Any]:
        """Return instantaneous telemetry for 3Hz UI pulse."""
        ...

    @abstractmethod
    async def cancel(self, session_id: str) -> None:
        """Cancel an ongoing prompt execution."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Teardown the agent process. Guarantees cleanup via SIGTERM/SIGKILL."""
        ...


# ---------------------------------------------------------------------------
# Adapter strategy base classes (MDS-61)
# ---------------------------------------------------------------------------

class NativeACPAdapter(AgentAdapter):
    """Base for agents that speak ACP directly over stdio.

    Concrete adapters: GeminiAdapter, OpenCodeAdapter, GooseAdapter, KiroAdapter.

    Subclasses must implement _build_launch_command() to produce the CLI
    invocation for the native binary. The connect/disconnect lifecycle,
    process management, and stream parsing are handled by shared plumbing.
    """

    @abstractmethod
    def _build_launch_command(self, config: "AgentConfig") -> List[str]:
        """Build the full CLI command list to spawn the native agent."""
        ...

    def _build_env(self, config: "AgentConfig") -> Dict[str, str]:
        """Build additional environment variables for the agent process.

        Override in subclasses to inject agent-specific env vars
        (e.g., GOOSE_MODEL for Goose).
        """
        return {}


class ExternalAdapterAgent(AgentAdapter):
    """Base for agents requiring an external wrapper binary (native → ACP).

    Concrete adapters: ClaudeAdapter, CursorAdapter, CodexAdapter.

    The wrapper binary (e.g., claude-agent-acp) is spawned as a subprocess
    and communicates via stdio ACP transport.
    """

    @abstractmethod
    def _build_launch_command(self, config: "AgentConfig") -> List[str]:
        """Build the full CLI command list to spawn the wrapper binary."""
        ...


class CustomAdapterAgent(AgentAdapter):
    """Base for agents with custom HTTP APIs (no ACP on wire).

    Concrete adapters: DroidAdapter.

    These adapters spawn the agent as an HTTP daemon and translate
    its custom API responses into ConsolidatedSessionUpdate objects.
    """

    @abstractmethod
    def _build_launch_command(self, config: "AgentConfig") -> List[str]:
        """Build the full CLI command list to spawn the agent daemon."""
        ...
