"""WebSocket uplink transport to Nautex cloud backend.

Abstracted behind GatewayUplinkTransport ABC so the transport can be
swapped (Redis, Kafka, etc.) without touching gateway logic.

WebSocket implementation handles:
- Persistent connection with exponential backoff reconnection
- GatewayWsEnvelope serialization/deserialization
- Unbounded asyncio.Queue for all outbound messages (single code path)
- on_reconnect callback for re-registration on reconnect
- Connection state events via GatewayEventBus
- Graceful shutdown

Reference: TRD-11, MDSNAUTX-27, MDSNAUTX-60, MDSNAUTX-62
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine, Optional

import websockets
from websockets.asyncio.client import ClientConnection

from .event_bus import GatewayEventBus, LocalEventKind
from .models import GatewayWsEnvelope

logger = logging.getLogger(__name__)

# Backoff config
INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 5.0
BACKOFF_FACTOR = 2.0

# Connection state payloads emitted to event bus
CONNECTION_STATE_CONNECTED = "connected"
CONNECTION_STATE_DISCONNECTED = "disconnected"
CONNECTION_STATE_RECONNECTING = "reconnecting"


class GatewayUplinkTransport(ABC):
    """Abstract transport interface for gateway <-> cloud communication.

    WebSocket is the initial implementation. This ABC ensures the transport
    can be swapped to Redis/Kafka without refactoring gateway logic.
    """

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def send(self, envelope: GatewayWsEnvelope) -> None: ...

    @abstractmethod
    async def send_raw(self, data: str) -> None: ...

    @abstractmethod
    def on_message(
        self, handler: Callable[[GatewayWsEnvelope], Coroutine[Any, Any, None]]
    ) -> None: ...

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...


class WebSocketUplink(GatewayUplinkTransport):
    """WebSocket client with queue-based sending and automatic reconnection.

    All outbound messages flow through a single asyncio.Queue. A dedicated
    _send_loop task drains the queue when connected and pauses (via
    asyncio.Event) when disconnected. No cap, no dual code paths.

    on_reconnect: async callback invoked after reconnection succeeds,
    before the send loop resumes draining. Used by GatewayNodeService
    to re-register and re-declare active sessions (MDSNAUTX-62).
    """

    def __init__(
        self,
        url: str,
        auth_token: Optional[str] = None,
        event_bus: Optional[GatewayEventBus] = None,
    ):
        self._url = url
        self._auth_token = auth_token
        self._event_bus = event_bus
        self._ws: Optional[ClientConnection] = None
        self._handler: Optional[
            Callable[[GatewayWsEnvelope], Coroutine[Any, Any, None]]
        ] = None
        self._on_reconnect: Optional[Callable[[], Coroutine[Any, Any, None]]] = None
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._connected_event = asyncio.Event()
        self._connected = False
        self._shutdown = False
        self._has_connected_once = False
        self._recv_task: Optional[asyncio.Task] = None
        self._send_task: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        self._reconnecting = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def buffered_count(self) -> int:
        return self._queue.qsize()

    def on_message(
        self, handler: Callable[[GatewayWsEnvelope], Coroutine[Any, Any, None]]
    ) -> None:
        self._handler = handler

    def on_reconnect(
        self, handler: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        """Set callback invoked on reconnection (before send loop resumes)."""
        self._on_reconnect = handler

    async def connect(self) -> None:
        """Establish WebSocket connection. Starts send + receive loops."""
        self._shutdown = False
        self._send_task = asyncio.create_task(self._send_loop())
        await self._establish(start_reconnect_on_fail=True)

    async def drain(self, timeout: float = 2.0) -> None:
        """Wait for the send queue to drain (up to timeout seconds)."""
        if self._queue.empty() or not self._connected:
            return
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Drain timeout, %d messages remaining", self._queue.qsize())

    async def disconnect(self) -> None:
        """Graceful shutdown — close connection, cancel tasks."""
        self._shutdown = True
        self._connected_event.set()  # unblock send loop so it can exit
        for task in (self._recv_task, self._send_task, self._reconnect_task):
            if task and not task.done():
                task.cancel()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._connected = False
        logger.info("Uplink disconnected")

    async def send(self, envelope: GatewayWsEnvelope) -> None:
        """Enqueue an envelope for sending. Non-blocking, unbounded."""
        self._queue.put_nowait(envelope.model_dump_json())

    async def send_raw(self, data: str) -> None:
        """Enqueue a raw JSON string for sending."""
        self._queue.put_nowait(data)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _emit_connection_state(self, state: str) -> None:
        """Publish connection state to event bus (non-blocking)."""
        if self._event_bus:
            self._event_bus.try_publish(LocalEventKind.CONNECTION_STATE, state)

    def _trigger_reconnect(self) -> None:
        """Request reconnection. No-op if already reconnecting or shutting down."""
        if self._shutdown or self._reconnecting:
            return
        self._reconnecting = True
        self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _establish(self, start_reconnect_on_fail: bool = True) -> None:
        """Single connection attempt."""
        headers = {}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        # Close any lingering WS from a previous failed attempt
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        try:
            self._ws = await websockets.connect(
                self._url, additional_headers=headers, open_timeout=5,
            )
            self._connected = True
            is_reconnect = self._has_connected_once
            self._has_connected_once = True
            logger.info("Uplink connected to %s", self._url)
            self._emit_connection_state(CONNECTION_STATE_CONNECTED)

            # On reconnect: re-register + re-declare before unblocking send loop
            if is_reconnect and self._on_reconnect:
                try:
                    await self._on_reconnect()
                except Exception as e:
                    logger.error("on_reconnect callback failed: %s", e)

            # Unblock send loop
            self._connected_event.set()

            # Cancel stale recv loop before starting a fresh one
            if self._recv_task and not self._recv_task.done():
                self._recv_task.cancel()
            self._recv_task = asyncio.create_task(self._recv_loop())
        except Exception as e:
            logger.warning("Connection failed: %s", e)
            self._connected = False
            # Clean up partially-opened socket
            if self._ws:
                try:
                    await self._ws.close()
                except Exception:
                    pass
                self._ws = None
            if start_reconnect_on_fail:
                self._trigger_reconnect()

    async def _send_loop(self) -> None:
        """Single consumer: drain queue when connected, pause when not."""
        while not self._shutdown:
            # Wait until connected
            await self._connected_event.wait()
            if self._shutdown:
                break

            try:
                data = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                await self._ws.send(data)
                self._queue.task_done()
            except Exception as e:
                # Send failed — re-enqueue at front and trigger reconnect
                logger.warning("Send failed, re-queuing: %s", e)
                self._queue.task_done()
                self._requeue_front(data)
                self._connected = False
                self._connected_event.clear()
                self._emit_connection_state(CONNECTION_STATE_DISCONNECTED)
                self._trigger_reconnect()

    def _requeue_front(self, data: str) -> None:
        """Put a failed message back at the front of the queue."""
        old_queue = self._queue
        self._queue = asyncio.Queue()
        self._queue.put_nowait(data)
        while not old_queue.empty():
            try:
                self._queue.put_nowait(old_queue.get_nowait())
            except asyncio.QueueEmpty:
                break

    async def _recv_loop(self) -> None:
        """Read messages from WebSocket and dispatch to handler."""
        try:
            async for raw in self._ws:
                if self._shutdown:
                    break
                try:
                    envelope = GatewayWsEnvelope.model_validate_json(raw)
                    if self._handler:
                        await self._handler(envelope)
                except Exception as e:
                    logger.warning("Failed to parse incoming message: %s", e)
        except websockets.ConnectionClosed:
            logger.info("Uplink connection closed")
        except Exception as e:
            logger.warning("Recv loop error: %s", e)
        finally:
            self._connected = False
            self._connected_event.clear()
            if not self._shutdown:
                self._emit_connection_state(CONNECTION_STATE_DISCONNECTED)
                self._trigger_reconnect()

    async def _reconnect(self) -> None:
        """Exponential backoff reconnection loop."""
        try:
            self._emit_connection_state(CONNECTION_STATE_RECONNECTING)
            backoff = INITIAL_BACKOFF
            while not self._shutdown:
                logger.info("Reconnecting in %.1fs... (queued=%d)", backoff, self._queue.qsize())
                await asyncio.sleep(backoff)
                if self._shutdown:
                    break
                await self._establish(start_reconnect_on_fail=False)
                if self._connected:
                    return
                backoff = min(backoff * BACKOFF_FACTOR, MAX_BACKOFF)
        except asyncio.CancelledError:
            raise
        finally:
            self._reconnecting = False
