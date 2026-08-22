"""Integration tests for GatewayNodeService with mock WebSocket server."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from nautex.gateway.config import GatewayNodeConfig
from nautex.gateway.event_bus import GatewayEventBus
from nautex.gateway.gateway_node_service import GatewayNodeService
from nautex.gateway.protocol import (
    GatewayWsEnvelope,
    HeartbeatPayload,
    ExecutePromptPayload,
    AgentLifecycleEvent,
    PermissionResponsePayload,
    PermissionRequestPayload,
    NODE_AGENT_LIFECYCLE,
    NODE_SESSION_UPDATE,
)
from nautex.gateway.uplink_transport import GatewayUplinkTransport, WebSocketUplink

from .dummy_ws_server import DummyWsServer


@pytest.fixture
def config(tmp_path):
    return GatewayNodeConfig(
        directory_scope=str(tmp_path),
        headless_mode=True,
        node_instance_id="test-node",
    )


class TestHeartbeat:

    @pytest.mark.asyncio
    async def test_heartbeat_sent(self, config):
        async with DummyWsServer() as server:
            config.uplink_url = f"ws://127.0.0.1:{server.actual_port}"
            uplink = WebSocketUplink(config.uplink_url)
            svc = GatewayNodeService(config, uplink=uplink)

            # Run for ~400ms — should get at least 1 heartbeat (3Hz = 333ms)
            task = asyncio.create_task(svc.start())
            await asyncio.sleep(0.5)
            await svc.shutdown()
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except (asyncio.CancelledError, Exception):
                pass

            heartbeats = [
                m for m in server.received
                if m.get("route") == "agw.node.heartbeat"
            ]
            assert len(heartbeats) >= 1
            payload = heartbeats[0]["payload"]
            assert payload["node_instance_id"] == "test-node"
            assert payload["status"] == "healthy"


class TestUplinkRouting:

    @pytest.mark.asyncio
    async def test_permission_response_routed(self, config):
        async with DummyWsServer() as server:
            config.uplink_url = f"ws://127.0.0.1:{server.actual_port}"
            config.auto_approve_privacy_gate = False
            uplink = WebSocketUplink(config.uplink_url)
            bus = GatewayEventBus()
            svc = GatewayNodeService(config, event_bus=bus, uplink=uplink)

            task = asyncio.create_task(svc.start())
            await asyncio.sleep(0.2)

            # Register a permission request
            req_task = asyncio.create_task(
                svc.permission_registry.register_request(
                    PermissionRequestPayload(
                        permission_id="perm-1",
                        session_id="ses-1",
                        tool_name="write_file",
                    )
                )
            )
            await asyncio.sleep(0.1)

            # Simulate cloud frontend response
            response_envelope = GatewayWsEnvelope(
                route="agw.frontend.permission_response",
                payload=PermissionResponsePayload(
                    permission_id="perm-1",
                    action="approve",
                ),
            )
            await svc._handle_uplink_message(response_envelope)

            result = await asyncio.wait_for(req_task, timeout=2.0)
            assert result.action == "approve"

            await svc.shutdown()
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except (asyncio.CancelledError, Exception):
                pass


class TestGracefulShutdown:

    @pytest.mark.asyncio
    async def test_shutdown_rejects_pending_permissions(self, config):
        config.auto_approve_privacy_gate = False
        bus = GatewayEventBus()
        svc = GatewayNodeService(config, event_bus=bus)

        task = asyncio.create_task(svc.start())
        await asyncio.sleep(0.1)

        from nautex.gateway.models import PermissionRequestPayload
        req_task = asyncio.create_task(
            svc.permission_registry.register_request(
                PermissionRequestPayload(
                    permission_id="perm-hang",
                    session_id="ses-1",
                    tool_name="terminal",
                )
            )
        )
        await asyncio.sleep(0.05)
        assert svc.permission_registry.pending_count == 1

        # Shutdown should reject the pending permission
        await svc.shutdown()
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except (asyncio.CancelledError, Exception):
            pass

        result = await asyncio.wait_for(req_task, timeout=1.0)
        assert result.action == "deny"

    @pytest.mark.asyncio
    async def test_shutdown_without_uplink(self, config):
        """Service runs and shuts down cleanly without WS uplink."""
        config.uplink_url = None
        svc = GatewayNodeService(config)

        task = asyncio.create_task(svc.start())
        await asyncio.sleep(0.2)
        await svc.shutdown()
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except (asyncio.CancelledError, Exception):
            pass


class TestBuffering:

    @pytest.mark.asyncio
    async def test_send_buffers_when_disconnected(self, config):
        uplink = WebSocketUplink("ws://127.0.0.1:1")  # port 1 — won't connect
        svc = GatewayNodeService(config, uplink=uplink)

        # Don't connect — just send directly via uplink
        envelope = GatewayWsEnvelope(
            route="agw.node.heartbeat",
            payload=HeartbeatPayload(
                node_instance_id="test",
                active_sessions_count=0,
            ),
        )
        await uplink.send(envelope)
        assert uplink.buffered_count == 1


class TestPromptLifecycle:

    @pytest.mark.asyncio
    async def test_unexpected_prompt_failure_crashes_agent_without_turn_complete(
        self,
        config,
    ):
        uplink = AsyncMock(spec=GatewayUplinkTransport)
        adapter = AsyncMock()
        adapter.prompt.side_effect = RuntimeError("adapter transport lost")
        svc = GatewayNodeService(config, uplink=uplink)
        svc._adapters["session-1"] = adapter
        svc._session_agents["session-1"] = "codex"

        await svc._dispatch_prompt(ExecutePromptPayload(
            session_id="session-1",
            agent_id="codex",
            prompt="Implement the task",
            turn_id="attempt-1",
        ))

        envelopes = [call.args[0] for call in uplink.send.await_args_list]
        session_updates = [
            envelope.payload
            for envelope in envelopes
            if envelope.route == NODE_SESSION_UPDATE
        ]
        lifecycle = [
            envelope.payload
            for envelope in envelopes
            if envelope.route == NODE_AGENT_LIFECYCLE
        ]

        assert [update.kind.value for update in session_updates] == [
            "turn_started",
            "agent_error",
        ]
        assert all(update.turn_id == "attempt-1" for update in session_updates)
        assert len(lifecycle) == 1
        assert lifecycle[0].event == AgentLifecycleEvent.CRASHED
        assert lifecycle[0].error_detail == "adapter transport lost"
        assert "session-1" not in svc._adapters
        adapter.disconnect.assert_awaited_once()
