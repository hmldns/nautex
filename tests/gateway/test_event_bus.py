"""Tests for gateway event bus publish/subscribe mechanics."""

import asyncio
import pytest

from nautex.gateway.event_bus import GatewayEventBus, LocalEventKind


class TestPublishSubscribe:

    @pytest.mark.asyncio
    async def test_basic_roundtrip(self):
        bus = GatewayEventBus()
        await bus.publish(LocalEventKind.PERMISSION_REQUEST, {"id": "p1"})
        kind, payload = await bus.subscribe()
        assert kind == LocalEventKind.PERMISSION_REQUEST
        assert payload == {"id": "p1"}

    @pytest.mark.asyncio
    async def test_fifo_ordering(self):
        bus = GatewayEventBus()
        await bus.publish(LocalEventKind.ACP_RAW_TRAFFIC, "first")
        await bus.publish(LocalEventKind.SESSION_UPDATE, "second")
        await bus.publish(LocalEventKind.AGENT_STATE_CHANGE, "third")

        k1, p1 = await bus.subscribe()
        k2, p2 = await bus.subscribe()
        k3, p3 = await bus.subscribe()

        assert p1 == "first"
        assert p2 == "second"
        assert p3 == "third"

    @pytest.mark.asyncio
    async def test_subscribe_blocks_until_publish(self):
        bus = GatewayEventBus()
        received = []

        async def consumer():
            kind, payload = await bus.subscribe()
            received.append(payload)

        async def producer():
            await asyncio.sleep(0.05)
            await bus.publish(LocalEventKind.SESSION_UPDATE, "delayed")

        await asyncio.gather(consumer(), producer())
        assert received == ["delayed"]

    @pytest.mark.asyncio
    async def test_concurrent_producer_consumer(self):
        bus = GatewayEventBus()
        results = []

        async def producer():
            for i in range(10):
                await bus.publish(LocalEventKind.ACP_RAW_TRAFFIC, i)

        async def consumer():
            for _ in range(10):
                _, payload = await bus.subscribe()
                results.append(payload)

        await asyncio.gather(producer(), consumer())
        assert results == list(range(10))

    @pytest.mark.asyncio
    async def test_no_deadlock_with_timeout(self):
        bus = GatewayEventBus()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(bus.subscribe(), timeout=0.05)


class TestTryPublish:

    @pytest.mark.asyncio
    async def test_try_publish_success(self):
        bus = GatewayEventBus()
        ok = bus.try_publish(LocalEventKind.SESSION_UPDATE, "data")
        assert ok is True
        assert bus.pending == 1

    @pytest.mark.asyncio
    async def test_try_publish_full_queue(self):
        bus = GatewayEventBus(maxsize=2)
        assert bus.try_publish(LocalEventKind.SESSION_UPDATE, "a") is True
        assert bus.try_publish(LocalEventKind.SESSION_UPDATE, "b") is True
        assert bus.try_publish(LocalEventKind.SESSION_UPDATE, "c") is False
        assert bus.pending == 2


class TestProperties:

    @pytest.mark.asyncio
    async def test_empty(self):
        bus = GatewayEventBus()
        assert bus.empty is True
        await bus.publish(LocalEventKind.SESSION_UPDATE, "x")
        assert bus.empty is False

    @pytest.mark.asyncio
    async def test_pending_count(self):
        bus = GatewayEventBus()
        assert bus.pending == 0
        await bus.publish(LocalEventKind.SESSION_UPDATE, "a")
        await bus.publish(LocalEventKind.SESSION_UPDATE, "b")
        assert bus.pending == 2
        await bus.subscribe()
        assert bus.pending == 1
