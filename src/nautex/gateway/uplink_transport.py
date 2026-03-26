"""WebSocket uplink transport to Nautex cloud backend.

Abstracted behind GatewayUplinkTransport ABC so the transport can be
swapped (Redis, Kafka, etc.) without touching gateway logic.

WebSocket implementation handles:
- Persistent connection with exponential backoff reconnection
- GatewayWsEnvelope serialization/deserialization
- Unsent message buffering during disconnects
- Graceful shutdown

Reference: TRD-11, MDSNAUTX-27
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine, List, Optional

import websockets
from websockets.asyncio.client import ClientConnection

from .models import GatewayWsEnvelope

logger = logging.getLogger(__name__)

# Backoff config
INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 30.0
BACKOFF_FACTOR = 2.0
BUFFER_LIMIT = 500


class GatewayUplinkTransport(ABC):
    """Abstract transport interface for gateway ↔ cloud communication.

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
    """WebSocket client with reconnection and message buffering."""

    def __init__(self, url: str, auth_token: Optional[str] = None):
        self._url = url
        self._auth_token = auth_token
        self._ws: Optional[ClientConnection] = None
        self._handler: Optional[
            Callable[[GatewayWsEnvelope], Coroutine[Any, Any, None]]
        ] = None
        self._buffer: List[str] = []
        self._connected = False
        self._shutdown = False
        self._recv_task: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def buffered_count(self) -> int:
        return len(self._buffer)

    def on_message(
        self, handler: Callable[[GatewayWsEnvelope], Coroutine[Any, Any, None]]
    ) -> None:
        self._handler = handler

    async def connect(self) -> None:
        """Establish WebSocket connection. Starts receive loop."""
        self._shutdown = False
        await self._connect_once()

    async def disconnect(self) -> None:
        """Graceful shutdown — close connection, cancel tasks."""
        self._shutdown = True
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._connected = False
        logger.info("Uplink disconnected")

    async def send_raw(self, data: str) -> None:
        """Send raw JSON string. Used for payloads outside the envelope union."""
        if self._connected and self._ws:
            try:
                await self._ws.send(data)
                return
            except Exception as e:
                logger.warning("Send failed, buffering: %s", e)
        if len(self._buffer) < BUFFER_LIMIT:
            self._buffer.append(data)

    async def send(self, envelope: GatewayWsEnvelope) -> None:
        """Send an envelope. Buffers if disconnected."""
        data = envelope.model_dump_json()
        if self._connected and self._ws:
            try:
                await self._ws.send(data)
                return
            except Exception as e:
                logger.warning("Send failed, buffering: %s", e)
                self._connected = False

        # Buffer for retry
        if len(self._buffer) < BUFFER_LIMIT:
            self._buffer.append(data)
        else:
            logger.warning("Buffer full (%d), dropping message", BUFFER_LIMIT)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _connect_once(self) -> None:
        """Single connection attempt."""
        headers = {}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        try:
            self._ws = await websockets.connect(self._url, additional_headers=headers)
            self._connected = True
            logger.info("Uplink connected to %s", self._url)

            # Flush buffer
            await self._flush_buffer()

            # Start receive loop
            self._recv_task = asyncio.create_task(self._recv_loop())
        except Exception as e:
            logger.warning("Connection failed: %s", e)
            self._connected = False
            if not self._shutdown:
                self._reconnect_task = asyncio.create_task(self._reconnect())

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
            if not self._shutdown:
                self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        """Exponential backoff reconnection loop."""
        backoff = INITIAL_BACKOFF
        while not self._shutdown:
            logger.info("Reconnecting in %.1fs...", backoff)
            await asyncio.sleep(backoff)
            if self._shutdown:
                break
            try:
                await self._connect_once()
                if self._connected:
                    return
            except Exception:
                pass
            backoff = min(backoff * BACKOFF_FACTOR, MAX_BACKOFF)

    async def _flush_buffer(self) -> None:
        """Send buffered messages after reconnection."""
        if not self._buffer or not self._ws:
            return
        flushed = 0
        while self._buffer:
            data = self._buffer[0]
            try:
                await self._ws.send(data)
                self._buffer.pop(0)
                flushed += 1
            except Exception:
                break
        if flushed:
            logger.info("Flushed %d buffered messages", flushed)
