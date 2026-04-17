"""Gateway node service — headless-first asyncio daemon.

Central router managing:
- WebSocket uplink to cloud backend
- Agent adapter subprocesses
- 4Hz heartbeat loop
- Permission registry
- Event bus for TUI decoupling
- Signal handling for graceful shutdown

Reference: MDSNAUTX-6, MDSNAUTX-12, MDSNAUTX-27
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Awaitable, Callable, Dict, List, Optional
from uuid import uuid4

from .config import GatewayNodeConfig, list_available_agents
from .event_bus import GatewayEventBus
from .indexer import FuzzyIndexer
from .models import AgentSessionConfig, MCPServerConfig, PromptContent, ConsolidatedSessionUpdate
from .protocol.enums import SessionUpdateKind
from .permission_registry import PermissionRegistry
from .adapters.base import AgentAdapter
from .adapters.acp_adapter import ACPAgentAdapter
from .protocol import (
    AgentDescriptorPayload,
    AgentLifecycleEvent,
    AgentLifecyclePayload,
    AgentSettingChangePayload,
    AgentSettings,
    ApplySettingsPayload,
    EnvironmentDescriptor,
    ExecutePromptPayload,
    GatewayWsEnvelope,
    HeartbeatPayload,
    NodeRegistrationPayload,
    PermissionRequestPayload,
    PermissionResponsePayload,
    RegistrationAckPayload,
    SearchRequestPayload,
    SearchResponsePayload,
    SearchResultItem,
    SessionAcknowledgedPayload,
    SessionDeclaredPayload,
    SpawnAgentPayload,
    StopAgentPayload,
    BACKEND_REGISTRATION_ACK,
    BACKEND_SESSION_ACKNOWLEDGED,
    BACKEND_APPLY_SETTINGS,
    BACKEND_SPAWN_AGENT,
    BACKEND_STOP_AGENT,
    FRONTEND_EXECUTE_PROMPT,
    FRONTEND_PERMISSION_RESPONSE,
    FRONTEND_SEARCH_REQUEST,
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
    ) -> None:
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
            self._uplink: Optional[GatewayUplinkTransport] = uplink
        elif config.uplink_url:
            self._uplink = WebSocketUplink(
                url=config.uplink_url,
                auth_token=config.auth_token,
                event_bus=self.event_bus,
            )
        else:
            self._uplink = None

        self._shutdown_event = asyncio.Event()
        self._session_agents: Dict[str, str] = {}          # session_id → agent_id
        self._adapters: Dict[str, AgentAdapter] = {}       # session_id → adapter
        self._monitor_tasks: Dict[str, asyncio.Task] = {}  # session_id → process monitor
        self._indexer: Optional[FuzzyIndexer] = None
        self._current_identity: Optional[IdentitySnapshot] = None
        self._anchor_env_id: Optional[str] = None

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

        if not self._uplink:
            return

        agents_info = list_available_agents()
        agents = [
            AgentDescriptorPayload(agent_id=agent_id, executable=info["registration"].executable, name=agent_id)
            for agent_id, info in agents_info.items() if info["installed"]
        ]

        if not agents:
            logger.warning("No agents detected — registering with empty agent list")

        payload = NodeRegistrationPayload(
            node_instance_id=self.config.node_instance_id,
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
        if not self._current_identity:
            return
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

    def _safe_task(self, coro: Awaitable[None], name: str = "") -> asyncio.Task:
        """Create a task with exception logging."""
        async def wrapper() -> None:
            try:
                await coro
            except Exception as e:
                logger.error("Task %s failed: %s", name, e, exc_info=True)
        return asyncio.create_task(wrapper())

    async def _handle_uplink_message(self, envelope: GatewayWsEnvelope) -> None:
        """Route incoming WebSocket messages to appropriate handlers."""
        route = envelope.route
        payload = envelope.payload

        if route == FRONTEND_PERMISSION_RESPONSE:
            if not isinstance(payload, PermissionResponsePayload):
                logger.warning("Expected PermissionResponsePayload, got %s", type(payload).__name__)
                return
            self.permission_registry.resolve_request(payload.permission_id, payload.action)

        elif route == FRONTEND_EXECUTE_PROMPT:
            if not isinstance(payload, ExecutePromptPayload):
                logger.warning("Expected ExecutePromptPayload, got %s", type(payload).__name__)
                return
            self._safe_task(self._dispatch_prompt(payload), "dispatch_prompt")

        elif route == BACKEND_REGISTRATION_ACK:
            if not isinstance(payload, RegistrationAckPayload):
                logger.warning("Expected RegistrationAckPayload, got %s", type(payload).__name__)
                return
            self._handle_registration_ack(payload)

        elif route == BACKEND_SESSION_ACKNOWLEDGED:
            if not isinstance(payload, SessionAcknowledgedPayload):
                logger.warning("Expected SessionAcknowledgedPayload, got %s", type(payload).__name__)
                return
            logger.info(
                "Session acknowledged: backend=%s acp=%s",
                payload.session_id,
                payload.acp_session_id,
            )

        elif route == BACKEND_SPAWN_AGENT:
            if not isinstance(payload, SpawnAgentPayload):
                logger.warning("Expected SpawnAgentPayload, got %s", type(payload).__name__)
                return
            self._safe_task(self._handle_spawn_agent(payload), "spawn_agent")

        elif route == BACKEND_STOP_AGENT:
            if not isinstance(payload, StopAgentPayload):
                logger.warning("Expected StopAgentPayload, got %s", type(payload).__name__)
                return
            self._safe_task(self._handle_stop_agent(payload), "stop_agent")

        elif route == BACKEND_APPLY_SETTINGS:
            if not isinstance(payload, ApplySettingsPayload):
                logger.warning("Expected ApplySettingsPayload, got %s", type(payload).__name__)
                return
            self._safe_task(self._handle_apply_settings(payload), "apply_settings")

        elif route == FRONTEND_SEARCH_REQUEST:
            if not isinstance(payload, SearchRequestPayload):
                logger.warning("Expected SearchRequestPayload, got %s", type(payload).__name__)
                return
            self._safe_task(self._handle_search_request(payload, envelope.correlation_id), "search_request")

        else:
            logger.debug("Unhandled uplink route: %s", route)

    def _handle_registration_ack(self, payload: RegistrationAckPayload) -> None:
        """Handle registration ack — write anchor file with environment_id."""
        if not payload.environment_id:
            return
        if not self._anchor_env_id:
            # First run — create anchor file
            if self._current_identity:
                create_anchor(self.config.directory_scope, payload.environment_id, self._current_identity)
            self._anchor_env_id = payload.environment_id
        logger.info("Registration ack: environment_id=%s", payload.environment_id)

    # ------------------------------------------------------------------
    # Prompt dispatch — spawn adapter if needed, forward to agent
    # ------------------------------------------------------------------

    async def _dispatch_prompt(self, payload: ExecutePromptPayload) -> None:
        """Route incoming prompt to the appropriate agent adapter."""
        if not payload.agent_id or not payload.prompt:
            logger.warning("Invalid prompt payload: agent=%s prompt=%s",
                           payload.agent_id, payload.prompt[:50] if payload.prompt else "")
            return

        logger.info("Dispatching prompt to %s (session=%s): %s",
                     payload.agent_id, payload.session_id, payload.prompt[:80])

        # Get adapter — must be started via SpawnAgent before prompting
        adapter = self._adapters.get(payload.session_id)
        if not adapter:
            logger.warning("No adapter for session %s — agent not started", payload.session_id)
            return

        # Synthesize turn_id for this prompt dispatch
        turn_id = str(uuid4())

        async def forward_with_session_id(csu: ConsolidatedSessionUpdate) -> None:
            try:
                csu.session_id = payload.session_id
                csu.turn_id = turn_id
                await self._forward_csu(csu)
            except Exception as e:
                logger.error("CSU forward failed (session=%s kind=%s): %s",
                             payload.session_id, csu.kind, e, exc_info=True)

        async def permission_with_session_id(prp: PermissionRequestPayload) -> PermissionResponsePayload:
            prp.session_id = payload.session_id
            return await self._handle_adapter_permission(prp)

        # Signal turn lifecycle
        await forward_with_session_id(ConsolidatedSessionUpdate(kind=SessionUpdateKind.TURN_STARTED))
        try:
            await adapter.prompt(
                session_id=payload.session_id,
                content=PromptContent(text=payload.prompt),
                on_update=forward_with_session_id,
                on_permission_request=permission_with_session_id,
            )
        except Exception as e:
            logger.error("Prompt execution failed for %s (session=%s): %s",
                         payload.agent_id, payload.session_id, e, exc_info=True)
        finally:
            await forward_with_session_id(ConsolidatedSessionUpdate(kind=SessionUpdateKind.TURN_COMPLETE))

    async def _handle_spawn_agent(self, payload: SpawnAgentPayload) -> None:
        """Spawn agent adapter for a session — dedicated command from backend.

        When acp_session_id is provided, loads existing session (resume).
        Otherwise creates a fresh session.
        """
        if not payload.agent_id or not payload.session_id:
            logger.warning("Invalid spawn payload: agent=%s session=%s",
                           payload.agent_id, payload.session_id)
            return

        if payload.session_id in self._adapters:
            logger.info("Session %s already has adapter, skipping", payload.session_id)
            return

        from .adapters.mock_adapter import MockTestingAgent, MOCK_AGENT_ID
        from .adapters.acp_adapter import create_adapter
        adapter: AgentAdapter
        if payload.agent_id == MOCK_AGENT_ID:
            adapter = MockTestingAgent()
        else:
            adapter = create_adapter(payload.agent_id, self.config.directory_scope)
        try:
            async def forward_system_event(csu: ConsolidatedSessionUpdate) -> None:
                if adapter.restoring:
                    return
                try:
                    csu.session_id = payload.session_id
                    await self._forward_csu(csu)
                except Exception as e:
                    logger.error("System event forward failed (session=%s kind=%s): %s",
                                 payload.session_id, csu.kind, e, exc_info=True)

            # Build session config from spawn payload + gateway defaults
            spawn_config = payload.session_config
            session_config = AgentSessionConfig(
                directory_scope=self.config.directory_scope,
                system_prompt_extension=spawn_config.system_prompt_extension if spawn_config else None,
                permissions=dict(spawn_config.permissions) if spawn_config else {},
                mcp_servers=[
                    MCPServerConfig(server_id=m.server_id, command=m.command, args=m.args, env=m.env)
                    for m in spawn_config.mcp_servers
                ] if spawn_config else [],
            )

            await adapter.connect(
                config=session_config,
                on_system_event=forward_system_event,
            )
            # Resume existing ACP session or create fresh
            if payload.acp_session_id:
                await adapter.load_session(payload.acp_session_id)
                logger.info("Session %s resumed with ACP session %s",
                            payload.session_id, payload.acp_session_id)

            self._adapters[payload.session_id] = adapter
            self._session_agents[payload.session_id] = payload.agent_id

            agent_pid = adapter.pid
            await self._emit_lifecycle(
                session_id=payload.session_id,
                event=AgentLifecycleEvent.STARTED,
                agent_id=payload.agent_id,
                pid=agent_pid,
                model_id=adapter.current_model,
                available_models=adapter.available_models,
                acp_session_id=adapter._acp_session_id or "",
            )
            self._monitor_tasks[payload.session_id] = asyncio.create_task(
                self._monitor_agent_process(adapter, payload.session_id, payload.agent_id, agent_pid)
            )
        except Exception as e:
            logger.error("Failed to spawn agent %s: %s", payload.agent_id, e)
            await self._emit_lifecycle(
                session_id=payload.session_id,
                event=AgentLifecycleEvent.CRASHED,
                agent_id=payload.agent_id,
            )

    async def _handle_stop_agent(self, payload: StopAgentPayload) -> None:
        """Stop agent adapter — dedicated command from backend."""
        adapter = self._adapters.get(payload.session_id)
        if not adapter:
            logger.warning("Session %s has no adapter, nothing to stop", payload.session_id)
            return

        # Cancel process monitor — we handle lifecycle directly (symmetric with start)
        monitor = self._monitor_tasks.pop(payload.session_id, None)
        if monitor and not monitor.done():
            monitor.cancel()

        try:
            await adapter.disconnect()
        except Exception as e:
            logger.warning("Error disconnecting adapter for session %s: %s", payload.session_id, e)

        self._adapters.pop(payload.session_id, None)
        self._session_agents.pop(payload.session_id, None)

        # Emit EXITED — symmetric with STARTED in _handle_spawn_agent
        await self._emit_lifecycle(
            session_id=payload.session_id,
            event=AgentLifecycleEvent.EXITED,
            agent_id=payload.agent_id,
        )

    async def _handle_apply_settings(self, payload: ApplySettingsPayload) -> None:
        """Apply settings from backend — call ACP set_session_model, confirm back."""
        adapter = self._adapters.get(payload.session_id)
        if not adapter:
            logger.warning("No adapter for settings change: session=%s", payload.session_id)
            return

        # Apply model change via ACP
        if payload.settings.model:
            success = await adapter.set_model(payload.settings.model)
            if success and self._uplink:
                # Confirm back to backend — creates the AgentSettingChangeItem
                confirm = AgentSettingChangePayload(
                    session_id=payload.session_id,
                    settings=AgentSettings(model=payload.settings.model),
                )
                envelope = GatewayWsEnvelope(route=NODE_AGENT_SETTING_CHANGE, payload=confirm)
                await self._uplink.send(envelope)
                logger.info("Settings applied: session=%s model=%s",
                            payload.session_id, payload.settings.model)

    async def _handle_search_request(
        self,
        payload: SearchRequestPayload,
        correlation_id: Optional[str] = None,
    ) -> None:
        """Handle file search request — query FuzzyIndexer, send response back."""
        if not self._uplink:
            return

        if not payload.query:
            logger.warning("Empty search query")
            return

        if not self._indexer:
            self._indexer = FuzzyIndexer(self.config.directory_scope, self.config.ignored_directories)
            await self._indexer.build_index()
            logger.info("FuzzyIndexer built: %d files", len(self._indexer._files))

        results = await self._indexer.search(payload.query, limit=payload.limit)
        response = SearchResponsePayload(
            results=[
                SearchResultItem(filepath=r.filepath, score=r.overall_score, snippets=[])
                for r in results
            ],
        )
        resp_envelope = GatewayWsEnvelope(
            route="agw.node.search_response",
            payload=response,
            correlation_id=correlation_id,
        )
        await self._uplink.send(resp_envelope)

    async def _monitor_agent_process(
        self,
        adapter: AgentAdapter,
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
        available_models: Optional[List[str]] = None,
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
        if not self._uplink:
            return
        payload = SessionDeclaredPayload(acp_session_id=acp_session_id, agent_id=agent_id)
        envelope = GatewayWsEnvelope(route=NODE_SESSION_DECLARED, payload=payload)
        await self._uplink.send(envelope)
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
    # Heartbeat — 4Hz global node health
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """4Hz heartbeat broadcasting node health to cloud."""
        while not self._shutdown_event.is_set():
            await asyncio.sleep(HEARTBEAT_INTERVAL)

            if self._uplink and self._uplink.is_connected:
                heartbeat = HeartbeatPayload(
                    node_instance_id=self.config.node_instance_id,
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
