"""Tests for permission registry — Future-based gating logic."""

import asyncio
import pytest

from nautex.gateway.event_bus import GatewayEventBus, LocalEventKind
from nautex.gateway.models import PermissionRequestPayload, PermissionResponsePayload
from nautex.gateway.permission_registry import PermissionRegistry


def make_request(pid: str = "p1", tool: str = "write_file") -> PermissionRequestPayload:
    return PermissionRequestPayload(
        permission_id=pid,
        session_id="ses-1",
        tool_name=tool,
        arguments={"path": "/tmp/test.txt"},
    )


class TestAutoApprove:

    @pytest.mark.asyncio
    async def test_auto_approve_resolves_immediately(self):
        bus = GatewayEventBus()
        reg = PermissionRegistry(bus, auto_approve=True)
        response = await reg.register_request(make_request("p1"))
        assert response.action == "approve"
        assert response.permission_id == "p1"
        assert reg.pending_count == 0

    @pytest.mark.asyncio
    async def test_auto_approve_multiple(self):
        bus = GatewayEventBus()
        reg = PermissionRegistry(bus, auto_approve=True)
        r1 = await reg.register_request(make_request("p1"))
        r2 = await reg.register_request(make_request("p2"))
        assert r1.action == "approve"
        assert r2.action == "approve"


class TestInteractiveGating:

    @pytest.mark.asyncio
    async def test_blocks_until_resolved(self):
        bus = GatewayEventBus()
        reg = PermissionRegistry(bus)
        resolved = []

        async def requester():
            resp = await reg.register_request(make_request("p1"))
            resolved.append(resp)

        async def approver():
            # Wait for event bus notification
            kind, payload = await bus.subscribe()
            assert kind == LocalEventKind.PERMISSION_REQUEST
            assert payload.permission_id == "p1"
            # Simulate user clicking approve
            reg.resolve_request("p1", "approve")

        await asyncio.gather(requester(), approver())
        assert len(resolved) == 1
        assert resolved[0].action == "approve"

    @pytest.mark.asyncio
    async def test_deny(self):
        bus = GatewayEventBus()
        reg = PermissionRegistry(bus)

        async def requester():
            return await reg.register_request(make_request("p1"))

        async def denier():
            await bus.subscribe()
            reg.resolve_request("p1", "deny")

        results = await asyncio.gather(requester(), denier())
        assert results[0].action == "deny"

    @pytest.mark.asyncio
    async def test_pending_count(self):
        bus = GatewayEventBus()
        reg = PermissionRegistry(bus)
        assert reg.pending_count == 0

        # Start request without resolving
        task = asyncio.create_task(reg.register_request(make_request("p1")))
        await asyncio.sleep(0.01)
        assert reg.pending_count == 1
        assert reg.is_pending("p1")

        reg.resolve_request("p1", "approve")
        await task
        assert reg.pending_count == 0


class TestHeadlessMode:

    @pytest.mark.asyncio
    async def test_delegates_to_cloud(self):
        bus = GatewayEventBus()
        delegated = []
        reg = PermissionRegistry(
            bus,
            headless_mode=True,
            on_delegate_to_cloud=lambda p: delegated.append(p),
        )

        task = asyncio.create_task(reg.register_request(make_request("p1")))
        await asyncio.sleep(0.01)

        # Callback was invoked
        assert len(delegated) == 1
        assert delegated[0].permission_id == "p1"

        # Still pending — waiting for WS response
        assert reg.is_pending("p1")

        # Simulate WS response
        reg.resolve_request("p1", "approve")
        resp = await task
        assert resp.action == "approve"


class TestRejectAll:

    @pytest.mark.asyncio
    async def test_reject_all_unblocks_futures(self):
        bus = GatewayEventBus()
        reg = PermissionRegistry(bus)

        # Start multiple requests
        t1 = asyncio.create_task(reg.register_request(make_request("p1")))
        t2 = asyncio.create_task(reg.register_request(make_request("p2")))
        t3 = asyncio.create_task(reg.register_request(make_request("p3")))
        await asyncio.sleep(0.01)

        assert reg.pending_count == 3
        count = reg.reject_all("test_disconnect")
        assert count == 3
        assert reg.pending_count == 0

        r1 = await t1
        r2 = await t2
        r3 = await t3
        assert r1.action == "deny"
        assert r2.action == "deny"
        assert r3.action == "deny"

    @pytest.mark.asyncio
    async def test_reject_all_empty(self):
        bus = GatewayEventBus()
        reg = PermissionRegistry(bus)
        count = reg.reject_all()
        assert count == 0


class TestResolveNonexistent:

    @pytest.mark.asyncio
    async def test_resolve_unknown_id_is_noop(self):
        bus = GatewayEventBus()
        reg = PermissionRegistry(bus)
        # Should not raise
        reg.resolve_request("nonexistent", "approve")
        assert reg.pending_count == 0
