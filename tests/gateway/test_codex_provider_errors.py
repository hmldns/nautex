from acp.schema import AgentMessageChunk

from nautex.gateway.adapters.codex.provider_errors import (
    parse_codex_provider_error,
)
from nautex.gateway.adapters.stream_consolidator import StreamConsolidator
from nautex.gateway.protocol import SessionUpdateKind


def _agent_message(text: str) -> AgentMessageChunk:
    return AgentMessageChunk.model_validate(
        {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": text},
        }
    )


def test_provider_error_envelope_becomes_agent_error() -> None:
    consolidator = StreamConsolidator(
        session_id="ses-provider-error",
        parse_agent_error=parse_codex_provider_error,
    )
    raw_error = (
        '{"type":"error","status":400,"error":'
        '{"type":"invalid_request_error","message":'
        '"The selected model requires a newer client."}}'
    )
    midpoint = len(raw_error) // 2

    assert consolidator.process(_agent_message(raw_error[:midpoint])) == []
    assert consolidator.process(_agent_message(raw_error[midpoint:])) == []

    result = consolidator.flush()
    assert len(result) == 1
    assert result[0].kind == SessionUpdateKind.AGENT_ERROR
    assert result[0].text == "The selected model requires a newer client."
    assert result[0].error_code == 400
    assert result[0].error_detail == raw_error


def test_ordinary_json_remains_agent_message() -> None:
    consolidator = StreamConsolidator(
        session_id="ses-json-message",
        parse_agent_error=parse_codex_provider_error,
    )
    raw_message = '{"type":"example","status":400,"message":"error-shaped prose"}'

    consolidator.process(_agent_message(raw_message))

    result = consolidator.flush()
    assert len(result) == 1
    assert result[0].kind == SessionUpdateKind.AGENT_MESSAGE
    assert result[0].text == raw_message


def test_error_like_json_with_extra_fields_remains_agent_message() -> None:
    consolidator = StreamConsolidator(
        session_id="ses-near-match",
        parse_agent_error=parse_codex_provider_error,
    )
    raw_message = (
        '{"type":"error","status":400,"error":'
        '{"type":"example","message":"This is ordinary output."},'
        '"explanation":"not the observed provider envelope"}'
    )

    consolidator.process(_agent_message(raw_message))

    result = consolidator.flush()
    assert len(result) == 1
    assert result[0].kind == SessionUpdateKind.AGENT_MESSAGE
    assert result[0].text == raw_message
