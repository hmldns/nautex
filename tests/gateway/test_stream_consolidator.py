"""Tests for stream consolidator semantic boundaries and error handling."""

import pytest
from acp.schema import (
    AgentMessageChunk,
    AgentThoughtChunk,
    AvailableCommandsUpdate,
    CurrentModeUpdate,
    ToolCallProgress,
    ToolCallStart,
)

from nautex.gateway.adapters.stream_consolidator import (
    ProtocolParseError,
    StreamConsolidator,
)
from nautex.gateway.protocol import (
    ConsolidatedSessionUpdate,
    SessionUpdateKind,
    ToolCallStatus,
    ToolKind,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_agent_message(text: str) -> AgentMessageChunk:
    return AgentMessageChunk.model_validate({
        "sessionUpdate": "agent_message_chunk",
        "content": {"type": "text", "text": text},
    })

def make_thought(text: str) -> AgentThoughtChunk:
    return AgentThoughtChunk.model_validate({
        "sessionUpdate": "agent_thought_chunk",
        "content": {"type": "text", "text": text},
    })

def make_tool_start(tool_call_id: str, title: str, kind: str = "edit") -> ToolCallStart:
    return ToolCallStart.model_validate({
        "sessionUpdate": "tool_call",
        "toolCallId": tool_call_id,
        "title": title,
        "status": "pending",
        "kind": kind,
    })

def make_tool_progress(tool_call_id: str, status: str, title: str = "", kind: str = "edit") -> ToolCallProgress:
    return ToolCallProgress.model_validate({
        "sessionUpdate": "tool_call_update",
        "toolCallId": tool_call_id,
        "status": status,
        "title": title or None,
        "kind": kind,
    })

def make_commands(count: int) -> AvailableCommandsUpdate:
    cmds = [{"id": f"cmd-{i}", "name": f"cmd{i}", "title": f"Command {i}", "description": f"Desc {i}"} for i in range(count)]
    return AvailableCommandsUpdate.model_validate({
        "sessionUpdate": "available_commands_update",
        "availableCommands": cmds,
    })

def make_mode_update(mode_id: str) -> CurrentModeUpdate:
    return CurrentModeUpdate.model_validate({
        "sessionUpdate": "current_mode_update",
        "currentModeId": mode_id,
    })

def collect(sc, update):
    return sc.process(update)


# ---------------------------------------------------------------------------
# Text Buffering
# ---------------------------------------------------------------------------

class TestTextBuffering:

    def test_single_word_chunks_buffered(self):
        sc = StreamConsolidator(session_id="ses-buf")
        assert collect(sc, make_agent_message("hello")) == []
        assert collect(sc, make_agent_message(" world")) == []
        assert sc.update_count == 0

    def test_sentence_end_flushes(self):
        sc = StreamConsolidator(session_id="ses-buf2")
        collect(sc, make_agent_message("hello"))
        result = collect(sc, make_agent_message(" world."))
        assert len(result) == 1
        assert result[0].text == "hello world."
        assert result[0].kind == SessionUpdateKind.AGENT_MESSAGE

    def test_newline_flushes(self):
        sc = StreamConsolidator(session_id="ses-nl")
        collect(sc, make_agent_message("line one"))
        result = collect(sc, make_agent_message("\n"))
        assert len(result) == 1
        assert result[0].text == "line one\n"

    def test_tool_call_flushes_pending_text(self):
        sc = StreamConsolidator(session_id="ses-flush")
        collect(sc, make_agent_message("pending text"))
        result = collect(sc, make_tool_start("tc-1", "write", "edit"))
        assert len(result) == 2
        assert result[0].kind == SessionUpdateKind.AGENT_MESSAGE
        assert result[0].text == "pending text"
        assert result[1].kind == SessionUpdateKind.TOOL_CALL

    def test_flush_at_end(self):
        sc = StreamConsolidator(session_id="ses-end")
        collect(sc, make_agent_message("trailing"))
        assert sc.update_count == 0
        result = sc.flush()
        assert len(result) == 1
        assert result[0].text == "trailing"

    def test_flush_empty_noop(self):
        sc = StreamConsolidator(session_id="ses-noop")
        assert sc.flush() == []


# ---------------------------------------------------------------------------
# Non-text updates (emitted immediately)
# ---------------------------------------------------------------------------

class TestNonTextUpdates:

    def test_tool_start(self):
        sc = StreamConsolidator(session_id="ses-1")
        result = collect(sc, make_tool_start("tc-1", "write file", "edit"))
        assert len(result) == 1
        assert result[0].kind == SessionUpdateKind.TOOL_CALL
        assert result[0].tool_call_id == "tc-1"
        assert result[0].tool_title == "write file"
        assert result[0].tool_status == ToolCallStatus.PENDING
        assert result[0].tool_kind == ToolKind.EDIT

    def test_tool_progress(self):
        sc = StreamConsolidator(session_id="ses-1")
        result = collect(sc, make_tool_progress("tc-1", "completed", "write file"))
        assert len(result) == 1
        assert result[0].kind == SessionUpdateKind.TOOL_CALL_UPDATE
        assert result[0].tool_status == ToolCallStatus.COMPLETED

    def test_commands(self):
        sc = StreamConsolidator(session_id="ses-1")
        result = collect(sc, make_commands(5))
        assert result[0].commands_count == 5

    def test_mode_update(self):
        sc = StreamConsolidator(session_id="ses-1")
        result = collect(sc, make_mode_update("code"))
        assert result[0].mode_id == "code"


# ---------------------------------------------------------------------------
# Full session sequence
# ---------------------------------------------------------------------------

class TestSessionSequence:

    def test_full_session(self):
        sc = StreamConsolidator(session_id="ses-seq")
        collect(sc, make_commands(3))
        collect(sc, make_thought("I will create a file.\n"))
        collect(sc, make_tool_start("tc-1", "write intro.sh", "edit"))
        collect(sc, make_tool_progress("tc-1", "completed", "intro.sh", "edit"))
        collect(sc, make_agent_message("Done.\n"))
        collect(sc, make_tool_start("tc-2", "bash", "execute"))
        collect(sc, make_tool_progress("tc-2", "completed", "run it", "execute"))
        collect(sc, make_agent_message("Output: hello."))
        sc.flush()
        # commands(1) + thought(1) + 2 tool(2) + message(1) + 2 tool(2) + flush message(1) = 8
        assert sc.update_count == 8


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

class TestTelemetry:

    def test_word_count(self):
        sc = StreamConsolidator(session_id="ses-tel")
        sc.process(make_agent_message("hello world.\n"))
        sc.process(make_agent_message("foo bar baz.\n"))
        assert sc.get_telemetry().processed_tokens_estimate == 5

    def test_active_tool(self):
        sc = StreamConsolidator(session_id="ses-at")
        sc.process(make_tool_start("tc-1", "write", "edit"))
        assert sc.get_telemetry().active_tool == "write"
        sc.process(make_tool_progress("tc-1", "completed", "write"))
        assert sc.get_telemetry().active_tool is None


# ---------------------------------------------------------------------------
# Replay deduplication
# ---------------------------------------------------------------------------

class TestReplayDeduplication:

    def test_replay_skips(self):
        sc = StreamConsolidator(session_id="ses-replay")
        sc.process(make_commands(1))
        sc.process(make_commands(2))
        assert sc.update_count == 2
        sc.start_replay()
        r1 = sc.process(make_commands(1))
        r2 = sc.process(make_commands(2))
        assert sc.update_count == 2  # no new updates
        r3 = sc.process(make_commands(3))
        assert sc.update_count == 3
        assert r3[0].commands_count == 3


# ---------------------------------------------------------------------------
# ProtocolParseError
# ---------------------------------------------------------------------------

class TestProtocolParseError:

    def test_invalid_update_raises(self):
        sc = StreamConsolidator(session_id="ses-err")
        class BadUpdate:
            session_update = "agent_message_chunk"
            @property
            def content(self):
                raise RuntimeError("broken")
        with pytest.raises(ProtocolParseError):
            sc.process(BadUpdate())

    def test_missing_session_update_raises(self):
        sc = StreamConsolidator(session_id="ses-fallback")
        class UnknownUpdate:
            pass
        with pytest.raises(ProtocolParseError):
            sc.process(UnknownUpdate())


# ---------------------------------------------------------------------------
# Accumulator integration
# ---------------------------------------------------------------------------

class TestAccumulatorIntegration:

    def test_tracks_tool_calls(self):
        sc = StreamConsolidator(session_id="ses-acc")
        sc.process(make_tool_start("tc-1", "write", "edit"))
        sc.process(make_tool_progress("tc-1", "completed", "write"))
        snapshot = sc.accumulator.snapshot()
        assert len(snapshot.tool_calls) == 1

    def test_tracks_messages(self):
        sc = StreamConsolidator(session_id="ses-acc2")
        sc.process(make_agent_message("hello.\n"))
        sc.process(make_agent_message("world.\n"))
        snapshot = sc.accumulator.snapshot()
        assert len(snapshot.agent_messages) == 2
