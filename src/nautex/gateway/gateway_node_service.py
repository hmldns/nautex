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
from .event_bus import GatewayEventBus
from .models import AgentDescriptor, AgentSessionConfig, PromptContent, ConsolidatedSessionUpdate
from .protocol.enums import SessionUpdateKind
from .permission_registry import PermissionRegistry
from .adapters.acp_adapter import ACPAgentAdapter
from .protocol import (
    AgentDescriptorPayload,
    AgentLifecycleEvent,
    AgentLifecyclePayload,
    AgentSettingChangePayload,
    AgentSettings,
    EnvironmentDescriptor,
    GatewayWsEnvelope,
    HeartbeatPayload,
    NodeRegistrationPayload,
    PermissionRequestPayload,
    PermissionResponsePayload,
    BACKEND_REGISTRATION_ACK,
    BACKEND_SESSION_ACKNOWLEDGED,
    BACKEND_APPLY_SETTINGS,
    BACKEND_SPAWN_AGENT,
    BACKEND_STOP_AGENT,
    FRONTEND_EXECUTE_PROMPT,
    FRONTEND_PERMISSION_RESPONSE,
    FRONTEND_SEARCH_REQUEST,
    SearchRequestPayload,
    SearchResponsePayload,
    NODE_REGISTER,
    NODE_SESSION_DECLARED,
    NODE_HEARTBEAT,
    NODE_AGENT_LIFECYCLE,
    NODE_AGENT_SETTING_CHANGE,
    NODE_PERMISSION_REQUEST,
    NODE_SESSION_UPDATE,
)
from .uplink_transport import GatewayUplinkTransport, WebSocketUplink
from .environment_anchor import (
    IdentitySnapshot, acquire_lock, release_lock,
    reconcile_at_startup, create_anchor, read_anchor,
)

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
                event_bus=self.event_bus,
            )
        else:
            self._uplink = None

        self._shutdown_event = asyncio.Event()
        self._session_agents: Dict[str, str] = {}     # session_id → agent_id
        self._adapters: Dict[str, ACPAgentAdapter] = {}  # session_id → adapter
        self._monitor_tasks: Dict[str, asyncio.Task] = {}  # session_id → process monitor
        self._indexer = None  # Lazy-init FuzzyIndexer

    async def start(self) -> None:
        """Run the daemon. Blocks until shutdown signal received."""
        import os
        import platform

        loop = asyncio.get_running_loop()

        # Install signal handlers
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal, sig)

        logger.info("Gateway node starting (headless=%s)", self.config.headless_mode)

        # Lockfile — prevent duplicate gateways per directory
        acquire_lock(self.config.directory_scope)

        # Environment anchor — reconcile identity before registration
        current_identity = IdentitySnapshot(
            hostname=platform.node(),
            directory_scope=self.config.directory_scope,
            username=os.getenv("USER", "unknown"),
        )
        self._current_identity = current_identity
        self._anchor_env_id = reconcile_at_startup(
            self.config.directory_scope,
            current_identity,
            headless=self.config.headless_mode,
        )

        try:
            # Connect uplink
            if self._uplink:
                self._uplink.on_message(self._handle_uplink_message)
                self._uplink.on_reconnect(self._handle_reconnect)
                await self._uplink.connect()

                # Register with backend — first message after connect
                await self._register(current_identity)

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

    async def _register(self, identity: IdentitySnapshot) -> None:
        """Send POOL_REGISTRATION with detected agents and environment."""
        import sys

        agents_info = list_available_agents()
        agents = [
            AgentDescriptorPayload(agent_id=agent_id, executable=info["registration"].executable, name=agent_id)
            for agent_id, info in agents_info.items() if info["installed"]
        ]

        if not agents:
            logger.warning("No agents detected — registering with empty agent list")

        payload = NodeRegistrationPayload(
            utility_instance_id=self.config.utility_instance_id,
            environment=EnvironmentDescriptor(
                hostname=identity.hostname,
                platform=sys.platform,
                directory_scope=identity.directory_scope,
                username=identity.username,
            ),
            agents=agents,
            environment_id=self._anchor_env_id,
        )

        envelope = GatewayWsEnvelope(route=NODE_REGISTER, payload=payload)
        await self._uplink.send(envelope)
        logger.info(
            "Registered with %d agent(s): %s",
            len(agents),
            ", ".join(a.agent_id for a in agents),
        )

    # ------------------------------------------------------------------
    # Reconnection — re-register and re-declare active sessions (MDSNAUTX-62)
    # ------------------------------------------------------------------

    async def _handle_reconnect(self) -> None:
        """Called by uplink after WebSocket reconnects (before buffer flush).

        Re-registers with backend and re-declares all active sessions
        to trigger UC2 auto-recovery on the backend side.
        """
        logger.info("Uplink reconnected — re-registering and re-declaring sessions")
        await self._register(self._current_identity)
        await self._redeclare_active_sessions()

    async def _redeclare_active_sessions(self) -> None:
        """Re-declare all active adapter sessions to backend via SESSION_DECLARED.

        Enables UC2 auto-recovery: backend matches these against
        AGENT_DISCONNECTED sessions and transitions them back to ACTIVE.
        """
        if not self._adapters:
            return

        for session_id, adapter in self._adapters.items():
            agent_id = self._session_agents.get(session_id, "")
            acp_session_id = adapter._acp_session_id or ""
            if not acp_session_id:
                continue
            await self._declare_session(acp_session_id, agent_id)
            logger.info(
                "Re-declared active session: session=%s acp=%s agent=%s",
                session_id, acp_session_id, agent_id,
            )

    # ------------------------------------------------------------------
    # Command dispatch — incoming WS messages from cloud
    # ------------------------------------------------------------------

    def _safe_task(self, coro, name: str = "") -> asyncio.Task:
        """Create a task with exception logging."""
        async def wrapper():
            try:
                await coro
            except Exception as e:
                logger.error("Task %s failed: %s", name, e, exc_info=True)
        return asyncio.create_task(wrapper())

    async def _handle_uplink_message(self, envelope: GatewayWsEnvelope) -> None:
        """Route incoming WebSocket messages to appropriate handlers."""
        route = envelope.route

        if route == FRONTEND_PERMISSION_RESPONSE:
            self.permission_registry.resolve_request(
                envelope.payload.permission_id,
                envelope.payload.action,
            )

        elif route == FRONTEND_EXECUTE_PROMPT:
            self._safe_task(self._dispatch_prompt(envelope.payload), "dispatch_prompt")

        elif route == BACKEND_REGISTRATION_ACK:
            self._handle_registration_ack(envelope.payload)

        elif route == BACKEND_SESSION_ACKNOWLEDGED:
            payload = envelope.payload
            logger.info(
                "Session acknowledged: backend=%s acp=%s",
                payload.get("session_id", "?") if isinstance(payload, dict) else getattr(payload, "session_id", "?"),
                payload.get("acp_session_id", "?") if isinstance(payload, dict) else getattr(payload, "acp_session_id", "?"),
            )

        elif route == BACKEND_SPAWN_AGENT:
            self._safe_task(self._handle_spawn_agent(envelope.payload), "spawn_agent")

        elif route == BACKEND_STOP_AGENT:
            self._safe_task(self._handle_stop_agent(envelope.payload), "stop_agent")

        elif route == BACKEND_APPLY_SETTINGS:
            self._safe_task(self._handle_apply_settings(envelope.payload), "apply_settings")

        elif route == FRONTEND_SEARCH_REQUEST:
            self._safe_task(self._handle_search_request(envelope), "search_request")

        else:
            logger.debug("Unhandled uplink route: %s", route)

    def _handle_registration_ack(self, payload) -> None:
        """Handle registration ack — write anchor file with environment_id."""
        env_id = payload.get("environment_id", "") if isinstance(payload, dict) else getattr(payload, "environment_id", "")
        if not env_id:
            return
        if not self._anchor_env_id:
            # First run — create anchor file
            create_anchor(self.config.directory_scope, env_id, self._current_identity)
            self._anchor_env_id = env_id
        logger.info("Registration ack: environment_id=%s", env_id)

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

        # Get adapter — must be started via SpawnAgent before prompting
        adapter = self._adapters.get(session_id)
        if not adapter:
            logger.warning("No adapter for session %s — agent not started", session_id)
            return

        # Synthesize turn_id for this prompt dispatch
        from uuid import uuid4
        turn_id = str(uuid4())

        async def forward_with_session_id(csu: ConsolidatedSessionUpdate) -> None:
            try:
                csu.session_id = session_id
                csu.turn_id = turn_id
                await self._forward_csu(csu)
            except Exception as e:
                logger.error("CSU forward failed (session=%s kind=%s): %s", session_id, csu.kind, e, exc_info=True)

        async def permission_with_session_id(prp: PermissionRequestPayload) -> PermissionResponsePayload:
            prp.session_id = session_id
            return await self._handle_adapter_permission(prp)

        # Signal turn lifecycle
        await forward_with_session_id(ConsolidatedSessionUpdate(kind=SessionUpdateKind.TURN_STARTED))
        try:
            await adapter.prompt(
                session_id=session_id,
                content=PromptContent(text=prompt_text),
                on_update=forward_with_session_id,
                on_permission_request=permission_with_session_id,
            )
        except Exception as e:
            logger.error("Prompt execution failed for %s (session=%s): %s", agent_id, session_id, e, exc_info=True)
        finally:
            await forward_with_session_id(ConsolidatedSessionUpdate(kind=SessionUpdateKind.TURN_COMPLETE))

    async def _handle_spawn_agent(self, payload) -> None:
        """Spawn agent adapter for a session — dedicated command from backend.

        When acp_session_id is provided, loads existing session (resume).
        Otherwise creates a fresh session.
        """
        agent_id = payload.agent_id if hasattr(payload, "agent_id") else payload.get("agent_id", "")
        session_id = payload.session_id if hasattr(payload, "session_id") else payload.get("session_id", "")
        acp_session_id = getattr(payload, "acp_session_id", None) or (payload.get("acp_session_id") if isinstance(payload, dict) else None)

        if not agent_id or not session_id:
            return

        if session_id in self._adapters:
            logger.info("Session %s already has adapter, skipping", session_id)
            return

        from .adapters.mock_adapter import MockTestingAgent, MOCK_AGENT_ID
        if agent_id == MOCK_AGENT_ID:
            adapter = MockTestingAgent()
        else:
            adapter = ACPAgentAdapter(agent_id, self.config.directory_scope)
        try:
            async def forward_system_event(csu: ConsolidatedSessionUpdate) -> None:
                if adapter.restoring:
                    return
                try:
                    csu.session_id = session_id
                    await self._forward_csu(csu)
                except Exception as e:
                    logger.error("System event forward failed (session=%s kind=%s): %s", session_id, csu.kind, e, exc_info=True)

            await adapter.connect(
                config=AgentSessionConfig(directory_scope=self.config.directory_scope),
                on_system_event=forward_system_event,
            )
            # Resume existing ACP session or create fresh
            if acp_session_id:
                await adapter.load_session(acp_session_id)
                logger.info("Session %s resumed with ACP session %s", session_id, acp_session_id)

            self._adapters[session_id] = adapter
            self._session_agents[session_id] = agent_id

            agent_pid = adapter.pid
            await self._emit_lifecycle(
                session_id=session_id,
                event=AgentLifecycleEvent.STARTED,
                agent_id=agent_id,
                pid=agent_pid,
                model_id=adapter.current_model,
                available_models=adapter.available_models,
                acp_session_id=adapter._acp_session_id or "",
            )
            self._monitor_tasks[session_id] = asyncio.create_task(
                self._monitor_agent_process(adapter, session_id, agent_id, agent_pid)
            )
        except Exception as e:
            logger.error("Failed to spawn agent %s: %s", agent_id, e)
            await self._emit_lifecycle(
                session_id=session_id,
                event=AgentLifecycleEvent.CRASHED,
                agent_id=agent_id,
            )

    async def _handle_stop_agent(self, payload) -> None:
        """Stop agent adapter — dedicated command from backend."""
        agent_id = payload.agent_id if hasattr(payload, "agent_id") else payload.get("agent_id", "")
        session_id = payload.session_id if hasattr(payload, "session_id") else payload.get("session_id", "")

        adapter = self._adapters.get(session_id)
        if not adapter:
            logger.warning("Session %s has no adapter, nothing to stop", session_id)
            return

        # Cancel process monitor — we handle lifecycle directly (symmetric with start)
        monitor = self._monitor_tasks.pop(session_id, None)
        if monitor and not monitor.done():
            monitor.cancel()

        try:
            await adapter.disconnect()
        except Exception as e:
            logger.warning("Error disconnecting adapter for session %s: %s", session_id, e)

        self._adapters.pop(session_id, None)
        self._session_agents.pop(session_id, None)

        # Emit EXITED — symmetric with STARTED in _handle_spawn_agent
        await self._emit_lifecycle(
            session_id=session_id,
            event=AgentLifecycleEvent.EXITED,
            agent_id=agent_id,
        )

    async def _handle_apply_settings(self, payload) -> None:
        """Apply settings from backend — call ACP set_session_model, confirm back."""
        session_id = payload.session_id if hasattr(payload, "session_id") else payload.get("session_id", "")
        settings = payload.settings if hasattr(payload, "settings") else payload.get("settings", {})

        if isinstance(settings, dict):
            settings = AgentSettings(**settings)

        adapter = self._adapters.get(session_id)
        if not adapter:
            logger.warning("No adapter for settings change: session=%s", session_id)
            return

        # Apply model change via ACP
        if settings.model:
            success = await adapter.set_model(settings.model)
            if success:
                # Confirm back to backend — creates the AgentSettingChangeItem
                confirm = AgentSettingChangePayload(
                    session_id=session_id,
                    settings=AgentSettings(model=settings.model),
                )
                envelope = GatewayWsEnvelope(route=NODE_AGENT_SETTING_CHANGE, payload=confirm)
                await self._uplink.send(envelope)
                logger.info("Settings applied: session=%s model=%s", session_id, settings.model)

    async def _handle_search_request(self, envelope: GatewayWsEnvelope) -> None:
        """Handle file search request — query FuzzyIndexer, send response back."""
        from .indexer import FuzzyIndexer

        payload = envelope.payload
        query = payload.query if hasattr(payload, "query") else payload.get("query", "")
        limit = payload.limit if hasattr(payload, "limit") else payload.get("limit", 15)

        if not self._indexer:
            self._indexer = FuzzyIndexer(self.config.directory_scope, self.config.ignored_directories)
            await self._indexer.build_index()
            logger.info("FuzzyIndexer built: %d files", len(self._indexer._files))

        results = await self._indexer.search(query, limit=limit)
        response = SearchResponsePayload(
            results=[{"filepath": r.filepath, "score": r.overall_score, "snippets": []} for r in results],
        )
        resp_envelope = GatewayWsEnvelope(
            route="agw.node.search_response",
            payload=response,
            correlation_id=envelope.correlation_id,
        )
        await self._uplink.send(resp_envelope)

    async def _monitor_agent_process(
        self,
        adapter: ACPAgentAdapter,
        session_id: str,
        agent_id: str,
        pid: int,
    ) -> None:
        """Watch agent process — emit EXITED/CRASHED when it dies."""
        proc = adapter._proc
        if not proc:
            return
        try:
            returncode = await proc.wait()
            # Process ended — determine if clean exit or crash
            if returncode == 0 or returncode == -15:  # 0 = clean, -15 = SIGTERM
                event = AgentLifecycleEvent.EXITED
            else:
                event = AgentLifecycleEvent.CRASHED
            await self._emit_lifecycle(
                session_id=session_id,
                event=event,
                agent_id=agent_id,
                pid=pid,
                return_code=returncode,
            )
            # Clean up adapter + monitor ref
            self._adapters.pop(session_id, None)
            self._session_agents.pop(session_id, None)
            self._monitor_tasks.pop(session_id, None)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Process monitor error for %s: %s", agent_id, e)

    async def _emit_lifecycle(
        self,
        session_id: str,
        event: AgentLifecycleEvent,
        agent_id: str,
        pid: int = 0,
        version: str = "",
        model_id: str = "",
        return_code: int = 0,
        available_models: list = None,
        acp_session_id: str = "",
    ) -> None:
        """Emit independent lifecycle event to backend."""
        if not self._uplink:
            return
        payload = AgentLifecyclePayload(
            session_id=session_id,
            acp_session_id=acp_session_id,
            event=event,
            agent_id=agent_id,
            pid=pid,
            version=version,
            model_id=model_id,
            return_code=return_code,
            available_models=available_models or [],
        )
        envelope = GatewayWsEnvelope(route=NODE_AGENT_LIFECYCLE, payload=payload)
        await self._uplink.send(envelope)
        logger.info("Lifecycle %s: session=%s agent=%s pid=%d", event.value, session_id, agent_id, pid)

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
                    active_sessions_count=len(self._adapters),
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
        """Clean shutdown: stop agents (with lifecycle), reject permissions, disconnect uplink, release lock."""
        # Stop all agents via symmetric flow — emits EXITED lifecycle via uplink
        for sid in list(self._adapters.keys()):
            agent_id = self._session_agents.get(sid, "")
            adapter = self._adapters.get(sid)
            if not adapter:
                continue

            monitor = self._monitor_tasks.pop(sid, None)
            if monitor and not monitor.done():
                monitor.cancel()

            try:
                await adapter.disconnect()
            except Exception as e:
                logger.warning("Adapter disconnect error for session %s: %s", sid, e)

            await self._emit_lifecycle(
                session_id=sid,
                event=AgentLifecycleEvent.EXITED,
                agent_id=agent_id,
            )
        self._adapters.clear()
        self._session_agents.clear()
        self._monitor_tasks.clear()

        # Reject all pending permissions so adapters don't hang
        rejected = self.permission_registry.reject_all("shutdown")
        if rejected:
            logger.info("Rejected %d pending permissions on shutdown", rejected)

        # Drain pending lifecycle events, then disconnect uplink
        if self._uplink:
            await self._uplink.drain()
            await self._uplink.disconnect()

        # Release lockfile
        release_lock(self.config.directory_scope)

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
