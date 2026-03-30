"""Gateway event bus — transient async queue decoupling network from TUI.

The event bus is a notification pipe only — it does NOT store state.
Actual permission state lives in PermissionRegistry.

Producers: PermissionRegistry (permission requests), GatewayNodeService (protocol logs)
Consumer: TextualGatewayMonitor (renders UI components from events)

Reference: MDSNAUTX-16, MDSNAUTX-17
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any, Tuple


class LocalEventKind(str, Enum):
    """Types of events flowing through the gateway event bus."""
    ACP_RAW_TRAFFIC = "acp_raw_traffic"
    PERMISSION_REQUEST = "permission_request"
    SESSION_UPDATE = "session_update"
    AGENT_STATE_CHANGE = "agent_state_change"
    CONNECTION_STATE = "connection_state"


class GatewayEventBus:
    """Transient asyncio.Queue pipeline for gateway events.

    Single-producer/single-consumer pattern. The TUI polls via subscribe(),
    the network/adapter layer pushes via publish().
    """

    def __init__(self, maxsize: int = 0):
        self._queue: asyncio.Queue[Tuple[LocalEventKind, Any]] = asyncio.Queue(
            maxsize=maxsize
        )

    async def publish(self, kind: LocalEventKind, payload: Any) -> None:
        """Push an event onto the bus. Non-blocking if queue has space."""
        await self._queue.put((kind, payload))

    async def subscribe(self) -> Tuple[LocalEventKind, Any]:
        """Wait for and return the next event. Blocks until available."""
        return await self._queue.get()

    def try_publish(self, kind: LocalEventKind, payload: Any) -> bool:
        """Non-blocking publish. Returns False if queue is full."""
        try:
            self._queue.put_nowait((kind, payload))
            return True
        except asyncio.QueueFull:
            return False

    @property
    def pending(self) -> int:
        """Number of events waiting to be consumed."""
        return self._queue.qsize()

    @property
    def empty(self) -> bool:
        return self._queue.empty()
