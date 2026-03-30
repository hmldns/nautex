"""Agent adapter interface.

Defines the normalization boundary between Nautex and third-party agent binaries.

Original MDS-61 proposed a hierarchy based on protocol type:
    NativeACPAdapter / ExternalAdapterAgent / CustomAdapterAgent

Probing all 8 agents revealed this distinction is irrelevant — every agent
uses the same ACP SDK stdio transport. The actual variance is in:
    - Execution model (delegated vs local vs partial)
    - Auth flow
    - Permission gating behavior
    - Env requirements

These are captured in SupportedAgentRegistration (gateway/models.py), not subclass hierarchy.
The adapter is now a single concrete class driven by config, not subclasses per agent.

Revised architecture:
    AgentAdapter (ABC)       — public interface for the gateway service
    └── ACPAgentAdapter      — concrete implementation using agent-client-protocol SDK
                               + SupportedAgentRegistration config for per-agent behavior

Reference: MDS-13, MDS-61 (revised)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Awaitable, Callable, Dict

from ..models import (
    AgentSessionConfig,
    AgentDescriptor,
    SupportedAgentRegistration,
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
    def descriptor(self) -> AgentDescriptor:
        """Agent identity and capabilities — populated from ACP runtime."""
        ...

    @property
    @abstractmethod
    def registration(self) -> SupportedAgentRegistration:
        """Static binary description from the registry."""
        ...


    @property
    @abstractmethod
    def state(self) -> AgentConnectionState:
        """Current lifecycle state."""
        ...

    @property
    def restoring(self) -> bool:
        """True while session is loading history — suppresses replayed updates."""
        return False

    @abstractmethod
    async def connect(
        self,
        config: AgentSessionConfig,
        on_system_event: Callable[[ConsolidatedSessionUpdate], Awaitable[None]],
    ) -> None:
        """Spawn agent process, initialize ACP, authenticate, create session.

        After connect, the adapter is ACTIVE and ready for prompts.
        The on_system_event callback receives out-of-band events
        (stderr, idle crashes) for the lifetime of the connection.
        """
        ...

    @abstractmethod
    async def create_session(self, config: GatewaySessionConfig) -> str:
        """Create a new agent session. Returns session ID."""
        ...

    @abstractmethod
    async def resume_session(self, session_id: str) -> None:
        """Invoke session/load for state reconciliation."""
        ...

    @abstractmethod
    async def prompt(
        self,
        session_id: str,
        content: PromptContent,
        on_update: Callable[[ConsolidatedSessionUpdate], Awaitable[None]],
        on_permission_request: Callable[
            [PermissionRequestPayload], Awaitable[PermissionResponsePayload]
        ],
    ) -> PromptResponse:
        """Send prompt and stream responses. Returns final result."""
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
        """Teardown the agent process. Guarantees cleanup."""
        ...
