"""Tests for gateway telemetry model serialization/deserialization."""

import json
import pytest
from nautex.gateway.telemetry import (
    NodeHeartbeatPayload,
    EphemeralSessionTelemetry,
)


class TestNodeHeartbeatPayload:

    def test_serialize_defaults(self):
        payload = NodeHeartbeatPayload(
            node_instance_id="inst-001",
            active_sessions_count=0,
        )
        data = payload.model_dump()
        assert data["node_instance_id"] == "inst-001"
        assert data["active_sessions_count"] == 0
        assert data["status"] == "healthy"

    def test_serialize_custom_status(self):
        payload = NodeHeartbeatPayload(
            node_instance_id="inst-002",
            active_sessions_count=3,
            status="degraded",
        )
        assert payload.status == "degraded"
        assert payload.active_sessions_count == 3

    def test_json_roundtrip(self):
        original = NodeHeartbeatPayload(
            node_instance_id="inst-rt",
            active_sessions_count=5,
            status="healthy",
        )
        json_str = original.model_dump_json()
        restored = NodeHeartbeatPayload.model_validate_json(json_str)
        assert restored == original

    def test_from_dict(self):
        data = {
            "node_instance_id": "inst-dict",
            "active_sessions_count": 1,
        }
        payload = NodeHeartbeatPayload.model_validate(data)
        assert payload.node_instance_id == "inst-dict"
        assert payload.status == "healthy"

    def test_missing_required_fields(self):
        with pytest.raises(Exception):
            NodeHeartbeatPayload.model_validate({})


class TestEphemeralSessionTelemetry:

    def test_serialize_with_active_tool(self):
        t = EphemeralSessionTelemetry(
            session_id="ses-001",
            active_tool="bash",
            processed_tokens_estimate=1500,
            is_typing=True,
        )
        data = t.model_dump()
        assert data["session_id"] == "ses-001"
        assert data["active_tool"] == "bash"
        assert data["processed_tokens_estimate"] == 1500
        assert data["is_typing"] is True

    def test_serialize_no_active_tool(self):
        t = EphemeralSessionTelemetry(
            session_id="ses-002",
            processed_tokens_estimate=0,
            is_typing=False,
        )
        data = t.model_dump()
        assert data["active_tool"] is None
        assert data["is_typing"] is False

    def test_json_roundtrip(self):
        original = EphemeralSessionTelemetry(
            session_id="ses-rt",
            active_tool="write_file",
            processed_tokens_estimate=3200,
            is_typing=True,
        )
        json_str = original.model_dump_json()
        restored = EphemeralSessionTelemetry.model_validate_json(json_str)
        assert restored == original

    def test_json_roundtrip_null_tool(self):
        original = EphemeralSessionTelemetry(
            session_id="ses-null",
            processed_tokens_estimate=0,
            is_typing=False,
        )
        json_str = original.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["active_tool"] is None
        restored = EphemeralSessionTelemetry.model_validate_json(json_str)
        assert restored == original

    def test_from_dict(self):
        data = {
            "session_id": "ses-dict",
            "processed_tokens_estimate": 42,
            "is_typing": True,
        }
        t = EphemeralSessionTelemetry.model_validate(data)
        assert t.session_id == "ses-dict"
        assert t.active_tool is None

    def test_missing_required_fields(self):
        with pytest.raises(Exception):
            EphemeralSessionTelemetry.model_validate({"session_id": "x"})
