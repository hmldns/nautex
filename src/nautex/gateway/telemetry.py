"""Gateway telemetry models — re-exported from protocol package.

Canonical definitions live in gateway.protocol.telemetry.
Reference: MDSNAUTX-25, MDSNAUTX-26
"""

from .protocol.telemetry import EphemeralSessionTelemetry, NodeHeartbeatPayload

__all__ = ["NodeHeartbeatPayload", "EphemeralSessionTelemetry"]
