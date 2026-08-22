from __future__ import annotations

import time

import pytest

from nautex.gateway.uplink_transport import (
    INITIAL_BACKOFF,
    MAX_BACKOFF,
    STABLE_CONNECTION_SECONDS,
    WebSocketUplink,
)
from nautex.gateway.models import GatewayWsEnvelope
from nautex.gateway.protocol import HeartbeatPayload, NODE_HEARTBEAT


@pytest.mark.asyncio
async def test_brief_reconnections_continue_exponential_backoff(monkeypatch):
    uplink = WebSocketUplink("ws://example.test")
    sleeps: list[float] = []

    async def no_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def establish(*, start_reconnect_on_fail: bool) -> None:
        assert start_reconnect_on_fail is False
        uplink._connected = True
        uplink._connected_at = time.monotonic()

    monkeypatch.setattr(
        "nautex.gateway.uplink_transport.asyncio.sleep",
        no_sleep,
    )
    monkeypatch.setattr(uplink, "_establish", establish)

    await uplink._reconnect()
    uplink._mark_disconnected()
    await uplink._reconnect()

    assert sleeps == [INITIAL_BACKOFF, INITIAL_BACKOFF * 2]
    assert uplink._reconnect_backoff == INITIAL_BACKOFF * 4


def test_stable_connection_resets_reconnect_backoff():
    uplink = WebSocketUplink("ws://example.test")
    uplink._reconnect_backoff = MAX_BACKOFF
    uplink._connected = True
    uplink._connected_event.set()
    uplink._connected_at = time.monotonic() - STABLE_CONNECTION_SECONDS - 1

    uplink._mark_disconnected()

    assert uplink._reconnect_backoff == INITIAL_BACKOFF
    assert not uplink.is_connected
    assert not uplink._connected_event.is_set()


class _FinishedSocket:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


@pytest.mark.asyncio
async def test_superseded_receive_loop_does_not_disconnect_new_socket():
    uplink = WebSocketUplink("ws://example.test")
    old_socket = _FinishedSocket()
    new_socket = _FinishedSocket()
    uplink._ws = new_socket
    uplink._connected = True
    uplink._connected_event.set()

    await uplink._recv_loop(old_socket)

    assert uplink.is_connected
    assert uplink._connected_event.is_set()


@pytest.mark.asyncio
async def test_reconnect_bootstrap_messages_precede_buffered_traffic():
    uplink = WebSocketUplink("ws://example.test")
    buffered = GatewayWsEnvelope(
        route=NODE_HEARTBEAT,
        payload=HeartbeatPayload(node_instance_id="node", active_sessions_count=0),
    )
    registration = GatewayWsEnvelope(
        route=NODE_HEARTBEAT,
        payload=HeartbeatPayload(node_instance_id="register", active_sessions_count=0),
    )
    declaration = GatewayWsEnvelope(
        route=NODE_HEARTBEAT,
        payload=HeartbeatPayload(node_instance_id="declare", active_sessions_count=0),
    )
    await uplink.send(buffered)

    uplink._bootstrap_messages = []
    await uplink.send(registration)
    await uplink.send(declaration)
    bootstrap = uplink._bootstrap_messages
    uplink._bootstrap_messages = None
    uplink._prepend_messages(bootstrap)

    queued = [await uplink._queue.get() for _ in range(3)]
    identities = [
        GatewayWsEnvelope.model_validate_json(value).payload.node_instance_id
        for value in queued
    ]
    assert identities == ["register", "declare", "node"]
