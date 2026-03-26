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

from .config import GatewayNodeConfig, list_available_agents
from .event_bus import GatewayEventBus, LocalEventKind
from .models import AgentDescriptor, AgentSessionConfig, PromptContent, ConsolidatedSessionUpdate
from .permission_registry import PermissionRegistry
from .adapters.acp_adapter import ACPAgentAdapter
from .protocol import (
    GatewayWsEnvelope,
    HeartbeatPayload,
    PermissionRequestPayload,
    PermissionResponsePayload,
    FRONTEND_EXECUTE_PROMPT,
    FRONTEND_PERMISSION_RESPONSE,
    BACKEND_SESSION_ACKNOWLEDGED,
    NODE_REGISTER,
    NODE_SESSION_DECLARED,
    NODE_HEARTBEAT,
    NODE_PERMISSION_REQUEST,
    NODE_SESSION_UPDATE,
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
        self._adapters: Dict[str, ACPAgentAdapter] = {}  # agent_id → adapter

    async def start(self) -> None:
        """Run the daemon. Blocks until shutdown signal received."""
        import os
        import platform

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

                # Register with backend — first message after connect
                await self._register(os.getcwd(), platform.node(), os.getenv("USER", "unknown"))

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
    # Registration — first message after WS connect
    # ------------------------------------------------------------------

    async def _register(self, directory_scope: str, hostname: str, username: str) -> None:
        """Send POOL_REGISTRATION with detected agents and environment.

        Uses raw JSON because NodeRegistrationPayload is a backend-only model
        not in the shared protocol union.
        """
        import json
        import sys

        # Detect installed agents
        agents_info = list_available_agents()
        agent_descriptors = []
        for agent_id, info in agents_info.items():
            if info["installed"]:
                reg = info["registration"]
                agent_descriptors.append({
                    "agent_id": agent_id,
                    "executable": reg.executable,
                    "name": agent_id,
                })

        if not agent_descriptors:
            logger.warning("No agents detected — registering with empty agent list")

        # Build and send as raw JSON — bypasses envelope model validation
        # because NodeRegistrationPayload is backend-only (not in GatewayPayload union)
        raw = json.dumps({
            "route": NODE_REGISTER,
            "payload": {
                "payload_type": "node_registration",
                "utility_instance_id": self.config.utility_instance_id,
                "environment": {
                    "hostname": hostname,
                    "platform": sys.platform,
                    "directory_scope": self.config.directory_scope,
                    "username": username,
                },
                "agents": agent_descriptors,
            },
        })
        await self._uplink.send_raw(raw)
        logger.info(
            "Registered with %d agent(s): %s",
            len(agent_descriptors),
            ", ".join(a["agent_id"] for a in agent_descriptors),
        )

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
            asyncio.create_task(self._dispatch_prompt(envelope.payload))

        elif route == BACKEND_SESSION_ACKNOWLEDGED:
            payload = envelope.payload
            logger.info(
                "Session acknowledged: backend=%s acp=%s",
                payload.get("session_id", "?") if isinstance(payload, dict) else getattr(payload, "session_id", "?"),
                payload.get("acp_session_id", "?") if isinstance(payload, dict) else getattr(payload, "acp_session_id", "?"),
            )

        else:
            logger.debug("Unhandled uplink route: %s", route)

    # ------------------------------------------------------------------
    # Prompt dispatch — spawn adapter if needed, forward to agent
    # ------------------------------------------------------------------

    async def _dispatch_prompt(self, payload) -> None:
        """Route incoming prompt to the appropriate agent adapter."""
        agent_id = payload.agent_id if hasattr(payload, "agent_id") else payload.get("agent_id", "")
        session_id = payload.session_id if hasattr(payload, "session_id") else payload.get("session_id", "")
        prompt_text = payload.prompt if hasattr(payload, "prompt") else payload.get("prompt", "")

        if not agent_id or not prompt_text:
            logger.warning("Invalid prompt payload: agent=%s prompt=%s", agent_id, prompt_text[:50] if prompt_text else "")
            return

        logger.info("Dispatching prompt to %s (session=%s): %s", agent_id, session_id, prompt_text[:80])

        # Get or create adapter for this agent
        adapter = self._adapters.get(agent_id)
        if not adapter:
            adapter = ACPAgentAdapter(agent_id, self.config.directory_scope)
            try:
                await adapter.connect(
                    config=AgentSessionConfig(directory_scope=self.config.directory_scope),
                    on_system_event=self._forward_csu,
                )
                self._adapters[agent_id] = adapter
            except Exception as e:
                import traceback
                traceback.print_exc()
                logger.error("Failed to connect adapter %s: %s", agent_id, e)
                return

        self._active_sessions[session_id] = agent_id

        async def forward_with_session_id(csu: ConsolidatedSessionUpdate) -> None:
            csu.session_id = session_id
            await self._forward_csu(csu)

        async def permission_with_session_id(prp: PermissionRequestPayload) -> PermissionResponsePayload:
            prp.session_id = session_id
            return await self._handle_adapter_permission(prp)

        try:
            await adapter.prompt(
                session_id=session_id,
                content=PromptContent(text=prompt_text),
                on_update=forward_with_session_id,
                on_permission_request=permission_with_session_id,
            )
        except Exception as e:
            logger.error("Prompt execution failed for %s: %s", agent_id, e)

    async def _declare_session(self, acp_session_id: str, agent_id: str) -> None:
        """Declare an ACP session to backend via SESSION_DECLARED."""
        import json
        raw = json.dumps({
            "route": NODE_SESSION_DECLARED,
            "payload": {
                "payload_type": "session_declared",
                "acp_session_id": acp_session_id,
                "agent_id": agent_id,
            },
        })
        await self._uplink.send_raw(raw)
        logger.info("Declared session: acp=%s agent=%s", acp_session_id, agent_id)

    async def _forward_csu(self, csu: ConsolidatedSessionUpdate) -> None:
        """Forward CSU to backend via WS uplink."""
        if not self._uplink:
            logger.warning("No uplink — cannot forward CSU")
            return
        logger.info("Forwarding CSU: kind=%s acp_session_id=%s", csu.kind, csu.acp_session_id)
        envelope = GatewayWsEnvelope(
            route=NODE_SESSION_UPDATE,
            payload=csu,
        )
        await self._uplink.send(envelope)

    async def _handle_adapter_permission(
        self, prp: PermissionRequestPayload
    ) -> PermissionResponsePayload:
        """Route permission request from adapter through permission registry."""
        return await self.permission_registry.register_request(prp)

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
                    route=NODE_HEARTBEAT,
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
        """Clean shutdown: disconnect adapters, reject permissions, disconnect uplink."""
        # Disconnect all active adapters
        for agent_id, adapter in self._adapters.items():
            try:
                await adapter.disconnect()
            except Exception as e:
                logger.warning("Adapter disconnect error for %s: %s", agent_id, e)
        self._adapters.clear()

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
            route=NODE_PERMISSION_REQUEST,
            payload=payload,
        )
        # Fire-and-forget — the response comes back via _handle_uplink_message
        asyncio.create_task(self._uplink.send(envelope))
