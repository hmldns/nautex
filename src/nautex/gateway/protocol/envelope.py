"""WebSocket message envelope shared between utility and backend.

All messages over the uplink are wrapped in this envelope.
The route field determines the handler. The payload is a discriminated
union — Pydantic auto-deserializes to the correct type via payload_type.
"""

from __future__ import annotations

from typing import Annotated, Optional

from pydantic import BaseModel, Field

from .payloads import PAYLOAD_DISCRIMINATOR, GatewayPayload


class GatewayWsEnvelope(BaseModel):
    """WebSocket message envelope between utility and cloud backend.

    The payload field is a discriminated union — each payload model has
    a payload_type literal that Pydantic uses to pick the correct type.

    Reference: TRD-11
    """
    route: str
    payload: Annotated[GatewayPayload, Field(discriminator=PAYLOAD_DISCRIMINATOR)]
    correlation_id: Optional[str] = None
