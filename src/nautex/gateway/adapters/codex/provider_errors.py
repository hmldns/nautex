"""Normalize provider failures that codex-acp emits as assistant text."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..stream_consolidator import ParsedAgentError


class _CodexProviderErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1)
    message: str = Field(min_length=1)


class _CodexProviderErrorEnvelope(BaseModel):
    """HTTP failure shape observed from codex-acp 1.1.0."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["error"]
    status: int = Field(ge=400, le=599)
    error: _CodexProviderErrorDetail


def parse_codex_provider_error(text: str) -> Optional[ParsedAgentError]:
    """Return an agent error only when the complete text is the known envelope."""
    try:
        envelope = _CodexProviderErrorEnvelope.model_validate_json(text)
    except ValidationError:
        return None
    return ParsedAgentError(
        message=envelope.error.message,
        code=envelope.status,
        detail=text,
    )
