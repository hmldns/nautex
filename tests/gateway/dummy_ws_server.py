"""Mock WebSocket server for gateway integration tests.

Echoes messages, tracks received envelopes, and can simulate
connection drops for testing reconnection logic.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, List, Optional

import websockets
from websockets.asyncio.server import ServerConnection, serve

logger = logging.getLogger(__name__)


class DummyWsServer:
    """Mock WebSocket server for testing gateway uplink."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self._host = host
        self._port = port
        self._server = None
        self._connections: List[ServerConnection] = []
        self.received: List[dict] = []
        self._responses: List[str] = []
        self._drop_after: Optional[int] = None
        self._msg_count = 0
        self.actual_port: int = 0

    def queue_response(self, data: dict) -> None:
        """Queue a message to send back on next receive."""
        self._responses.append(json.dumps(data))

    def drop_after(self, n: int) -> None:
        """Close connection after receiving n messages."""
        self._drop_after = n

    async def start(self) -> int:
        """Start server, return actual port."""
        self._server = await serve(
            self._handler,
            self._host,
            self._port,
        )
        # Get actual bound port
        for sock in self._server.sockets:
            self.actual_port = sock.getsockname()[1]
            break
        return self.actual_port

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handler(self, ws: ServerConnection) -> None:
        self._connections.append(ws)
        try:
            async for raw in ws:
                self._msg_count += 1
                try:
                    data = json.loads(raw)
                    self.received.append(data)
                except json.JSONDecodeError:
                    self.received.append({"raw": raw})

                # Send queued responses
                while self._responses:
                    resp = self._responses.pop(0)
                    await ws.send(resp)

                # Simulate drop
                if self._drop_after and self._msg_count >= self._drop_after:
                    await ws.close()
                    return
        except websockets.ConnectionClosed:
            pass
        finally:
            if ws in self._connections:
                self._connections.remove(ws)

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()
