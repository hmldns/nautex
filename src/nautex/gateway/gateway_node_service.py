"""Gateway node service — headless-first asyncio daemon.

Central router managing:
- WebSocket uplink to cloud backend
- Agent adapter subprocesses
- 3Hz heartbeat loop
- Permission registry
- Event bus for TUI decoupling
- Signal handling for graceful shutdown

Reference: MDSNAUTX-6, MDSNAUTX-12, MDSNAUTX-27
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Dict, Optional

from .config import GatewayNodeConfig
from .event_bus import GatewayEventBus, LocalEventKind
from .permission_registry import PermissionRegistry
from .protocol import (
    GatewayWsEnvelope,
    HeartbeatPayload,
    PermissionRequestPayload,
    FRONTEND_EXECUTE_PROMPT,
    FRONTEND_PERMISSION_RESPONSE,
    UTILITY_HEARTBEAT,
    UTILITY_PERMISSION_REQUEST,
)
from .uplink_transport import GatewayUplinkTransport, WebSocketUplink

logger = logging.getLogger(__name__)

# Heartbeat interval — 4Hz
HEARTBEAT_INTERVAL = 0.25


class GatewayNodeService:
    """Headless-first asyncio daemon orchestrating agents and transports.

    Call start() to run the main loop. SIGTERM/SIGINT trigger graceful
    shutdown via _shutdown_event.
    """

    def __init__(
        self,
        config: GatewayNodeConfig,
        event_bus: Optional[GatewayEventBus] = None,
        uplink: Optional[GatewayUplinkTransport] = None,
    ):
        self.config = config
        self.event_bus = event_bus or GatewayEventBus()
        self.permission_registry = PermissionRegistry(
            event_bus=self.event_bus,
            auto_approve=config.auto_approve_privacy_gate,
            headless_mode=config.headless_mode,
            on_delegate_to_cloud=self._delegate_permission_to_cloud,
        )

        # Transport — create WebSocket uplink if URL configured
        if uplink:
            self._uplink = uplink
        elif config.uplink_url:
            self._uplink = WebSocketUplink(
                url=config.uplink_url,
                auth_token=config.auth_token,
            )
        else:
            self._uplink = None

        self._shutdown_event = asyncio.Event()
        self._active_sessions: Dict[str, str] = {}  # session_id → agent_id

    async def start(self) -> None:
        """Run the daemon. Blocks until shutdown signal received."""
        loop = asyncio.get_running_loop()

        # Install signal handlers
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal, sig)

        logger.info("Gateway node starting (headless=%s)", self.config.headless_mode)

        try:
            # Connect uplink
            if self._uplink:
                self._uplink.on_message(self._handle_uplink_message)
                await self._uplink.connect()

            # Run concurrent tasks — gather instead of TaskGroup for Python 3.10
            await asyncio.gather(
                self._heartbeat_loop(),
                self._wait_for_shutdown(),
                return_exceptions=True,
            )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Service loop error: %s", e)
        finally:
            await self._teardown()

    async def shutdown(self) -> None:
        """Trigger graceful shutdown from outside."""
        self._shutdown_event.set()

    # ------------------------------------------------------------------
    # Command dispatch — incoming WS messages from cloud
    # ------------------------------------------------------------------

    async def _handle_uplink_message(self, envelope: GatewayWsEnvelope) -> None:
        """Route incoming WebSocket messages to appropriate handlers."""
        route = envelope.route

        if route == FRONTEND_PERMISSION_RESPONSE:
            self.permission_registry.resolve_request(
                envelope.payload.permission_id,
                envelope.payload.action,
            )

        elif route == FRONTEND_EXECUTE_PROMPT:
            await self.event_bus.publish(
                LocalEventKind.SESSION_UPDATE, envelope.payload
            )

        else:
            logger.debug("Unhandled uplink route: %s", route)

    # ------------------------------------------------------------------
    # Heartbeat — 3Hz global node health
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """3Hz heartbeat broadcasting node health to cloud."""
        while not self._shutdown_event.is_set():
            await asyncio.sleep(HEARTBEAT_INTERVAL)

            if self._uplink and self._uplink.is_connected:
                heartbeat = HeartbeatPayload(
                    utility_instance_id=self.config.utility_instance_id,
                    active_sessions_count=len(self._active_sessions),
                )
                envelope = GatewayWsEnvelope(
                    route=UTILITY_HEARTBEAT,
                    payload=heartbeat,
                )
                await self._uplink.send(envelope)

    # ------------------------------------------------------------------
    # Signal handling & teardown
    # ------------------------------------------------------------------

    def _handle_signal(self, sig: signal.Signals) -> None:
        logger.info("Received %s, initiating shutdown", sig.name)
        self._shutdown_event.set()

    async def _wait_for_shutdown(self) -> None:
        """Wait for shutdown event."""
        await self._shutdown_event.wait()

    async def _teardown(self) -> None:
        """Clean shutdown: reject permissions, disconnect uplink."""
        # Reject all pending permissions so adapters don't hang
        rejected = self.permission_registry.reject_all("shutdown")
        if rejected:
            logger.info("Rejected %d pending permissions on shutdown", rejected)

        # Disconnect uplink
        if self._uplink:
            await self._uplink.disconnect()

        logger.info("Gateway node stopped")

    # ------------------------------------------------------------------
    # Permission delegation
    # ------------------------------------------------------------------

    def _delegate_permission_to_cloud(self, payload: PermissionRequestPayload) -> None:
        """Send permission request to cloud frontend via WS uplink."""
        if not self._uplink:
            logger.warning("No uplink — cannot delegate permission %s", payload.permission_id)
            return
        envelope = GatewayWsEnvelope(
            route=UTILITY_PERMISSION_REQUEST,
            payload=payload,
        )
        # Fire-and-forget — the response comes back via _handle_uplink_message
        asyncio.create_task(self._uplink.send(envelope))
