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
from nautex.gateway.models import ConsolidatedSessionUpdate


# ---------------------------------------------------------------------------
# Fixtures — construct real SDK update objects
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
    """Process an update and return flat list of emitted CSUs."""
    return sc.process(update)


# ---------------------------------------------------------------------------
# Tests — Text Buffering (sentence boundary batching)
# ---------------------------------------------------------------------------

class TestTextBuffering:

    def test_single_word_chunks_buffered(self):
        """Single-word chunks should be buffered, not emitted individually."""
        sc = StreamConsolidator(session_id="ses-buf")
        assert collect(sc, make_agent_message("hello")) == []
        assert collect(sc, make_agent_message(" world")) == []
        assert sc.update_count == 0  # nothing emitted yet

    def test_sentence_end_flushes(self):
        """Period at end triggers flush."""
        sc = StreamConsolidator(session_id="ses-buf2")
        collect(sc, make_agent_message("hello"))
        result = collect(sc, make_agent_message(" world."))
        assert len(result) == 1
        assert result[0].data["text"] == "hello world."

    def test_newline_flushes(self):
        """Newline triggers flush."""
        sc = StreamConsolidator(session_id="ses-nl")
        collect(sc, make_agent_message("line one"))
        result = collect(sc, make_agent_message("\n"))
        assert len(result) == 1
        assert result[0].data["text"] == "line one\n"

    def test_double_newline_flushes(self):
        """Double newline (paragraph break) triggers flush."""
        sc = StreamConsolidator(session_id="ses-dnl")
        collect(sc, make_agent_message("paragraph one"))
        result = collect(sc, make_agent_message("\n\n"))
        assert len(result) == 1
        assert result[0].data["text"] == "paragraph one\n\n"

    def test_tool_call_flushes_pending_text(self):
        """Non-text update flushes buffered text first."""
        sc = StreamConsolidator(session_id="ses-flush")
        collect(sc, make_agent_message("pending text"))
        result = collect(sc, make_tool_start("tc-1", "write", "edit"))
        # Should get 2: flushed text + tool_call
        assert len(result) == 2
        assert result[0].kind == "agent_message_chunk"
        assert result[0].data["text"] == "pending text"
        assert result[1].kind == "tool_call"

    def test_thought_to_message_flushes(self):
        """Switching from thought to message flushes thought buffer."""
        sc = StreamConsolidator(session_id="ses-switch")
        collect(sc, make_thought("thinking."))  # flushed by period
        result = collect(sc, make_agent_message("result."))
        assert len(result) == 1
        assert result[0].kind == "agent_message_chunk"

    def test_flush_at_end(self):
        """Explicit flush() emits remaining buffer."""
        sc = StreamConsolidator(session_id="ses-end")
        collect(sc, make_agent_message("trailing"))
        assert sc.update_count == 0
        result = sc.flush()
        assert len(result) == 1
        assert result[0].data["text"] == "trailing"
        assert sc.update_count == 1

    def test_flush_empty_noop(self):
        """Flush with no pending text returns empty."""
        sc = StreamConsolidator(session_id="ses-noop")
        assert sc.flush() == []

    def test_multiple_sentences_batched(self):
        """Multiple sentence chunks accumulate until boundary."""
        sc = StreamConsolidator(session_id="ses-multi")
        collect(sc, make_agent_message("First"))
        collect(sc, make_agent_message(" sentence"))
        result = collect(sc, make_agent_message(".\n"))
        assert len(result) == 1
        assert result[0].data["text"] == "First sentence.\n"


# ---------------------------------------------------------------------------
# Tests — Non-text updates (emitted immediately)
# ---------------------------------------------------------------------------

class TestNonTextUpdates:

    def test_tool_start(self):
        sc = StreamConsolidator(session_id="ses-1")
        result = collect(sc, make_tool_start("tc-1", "write file", "edit"))
        assert len(result) == 1
        assert result[0].kind == "tool_call"
        assert result[0].data["tool_call_id"] == "tc-1"

    def test_tool_progress(self):
        sc = StreamConsolidator(session_id="ses-1")
        result = collect(sc, make_tool_progress("tc-1", "completed", "write file"))
        assert len(result) == 1
        assert result[0].kind == "tool_call_update"

    def test_commands(self):
        sc = StreamConsolidator(session_id="ses-1")
        result = collect(sc, make_commands(5))
        assert len(result) == 1
        assert result[0].data["count"] == 5

    def test_mode_update(self):
        sc = StreamConsolidator(session_id="ses-1")
        result = collect(sc, make_mode_update("code"))
        assert len(result) == 1
        assert result[0].data["mode_id"] == "code"


# ---------------------------------------------------------------------------
# Tests — Full session sequence
# ---------------------------------------------------------------------------

class TestSessionSequence:

    def test_full_session(self):
        sc = StreamConsolidator(session_id="ses-seq")

        collect(sc, make_commands(3))
        collect(sc, make_thought("I will create a file.\n"))
        collect(sc, make_tool_start("tc-1", "write intro.sh", "edit"))
        collect(sc, make_tool_progress("tc-1", "in_progress", kind="edit"))
        collect(sc, make_tool_progress("tc-1", "completed", "intro.sh", "edit"))
        collect(sc, make_agent_message("I created the file.\n"))
        collect(sc, make_tool_start("tc-2", "bash", "execute"))
        collect(sc, make_tool_progress("tc-2", "completed", "run it", "execute"))
        collect(sc, make_agent_message("Done."))
        sc.flush()

        # commands(1) + thought(1) + tool_start(1) + 2 progress + message(1)
        # + tool_start(1) + progress(1) + message(1) = 9
        assert sc.update_count == 9


# ---------------------------------------------------------------------------
# Tests — Telemetry
# ---------------------------------------------------------------------------

class TestTelemetry:

    def test_word_count_accumulates(self):
        sc = StreamConsolidator(session_id="ses-tel")
        sc.process(make_agent_message("hello world.\n"))  # 2 words
        sc.process(make_agent_message("foo bar baz.\n"))   # 3 words
        t = sc.get_telemetry()
        assert t.processed_tokens_estimate == 5

    def test_is_typing_on_text(self):
        sc = StreamConsolidator(session_id="ses-typ")
        sc.process(make_agent_message("typing now"))
        assert sc.get_telemetry().is_typing is True

    def test_is_typing_off_on_tool(self):
        sc = StreamConsolidator(session_id="ses-typ2")
        sc.process(make_agent_message("typing.\n"))
        assert sc.get_telemetry().is_typing is True
        sc.process(make_tool_start("tc-1", "bash", "execute"))
        assert sc.get_telemetry().is_typing is False

    def test_active_tool_tracks(self):
        sc = StreamConsolidator(session_id="ses-at")
        sc.process(make_tool_start("tc-1", "write", "edit"))
        assert sc.get_telemetry().active_tool == "write"
        sc.process(make_tool_progress("tc-1", "completed", "write"))
        assert sc.get_telemetry().active_tool is None


# ---------------------------------------------------------------------------
# Tests — Replay deduplication
# ---------------------------------------------------------------------------

class TestReplayDeduplication:

    def test_replay_skips_old_updates(self):
        sc = StreamConsolidator(session_id="ses-replay")

        # Process 3 tool updates normally (non-text, so emitted immediately)
        sc.process(make_tool_start("tc-1", "a", "edit"))
        sc.process(make_tool_progress("tc-1", "completed", "a"))
        sc.process(make_commands(2))
        assert sc.update_count == 3

        sc.start_replay()

        # Replay sends 3 updates — should be skipped
        r1 = sc.process(make_tool_start("tc-1", "a", "edit"))
        r2 = sc.process(make_tool_progress("tc-1", "completed", "a"))
        r3 = sc.process(make_commands(2))
        assert r1[0].kind == "replay_skip"
        assert r2[0].kind == "replay_skip"
        assert r3[0].kind == "replay_skip"
        assert sc.update_count == 3

        # New update after replay — should pass through
        r4 = sc.process(make_commands(1))
        assert r4[0].kind == "available_commands_update"
        assert sc.update_count == 4

    def test_stop_replay_clears(self):
        sc = StreamConsolidator(session_id="ses-replay2")
        sc.process(make_commands(1))
        sc.start_replay()
        r = sc.process(make_commands(1))
        assert r[0].kind == "replay_skip"
        sc.stop_replay()
        r = sc.process(make_commands(1))
        assert r[0].kind == "available_commands_update"


# ---------------------------------------------------------------------------
# Tests — ProtocolParseError
# ---------------------------------------------------------------------------

class TestProtocolParseError:

    def test_invalid_update_raises(self):
        sc = StreamConsolidator(session_id="ses-err")
        class BadUpdate:
            session_update = "agent_message_chunk"
            @property
            def content(self):
                raise RuntimeError("broken content")
        with pytest.raises(ProtocolParseError):
            sc.process(BadUpdate())

    def test_missing_session_update_raises(self):
        sc = StreamConsolidator(session_id="ses-fallback")
        class UnknownUpdate:
            pass
        with pytest.raises(ProtocolParseError):
            sc.process(UnknownUpdate())


# ---------------------------------------------------------------------------
# Tests — Accumulator integration
# ---------------------------------------------------------------------------

class TestAccumulatorIntegration:

    def test_accumulator_tracks_tool_calls(self):
        sc = StreamConsolidator(session_id="ses-acc")
        sc.process(make_tool_start("tc-1", "write", "edit"))
        sc.process(make_tool_progress("tc-1", "completed", "write"))
        snapshot = sc.accumulator.snapshot()
        assert len(snapshot.tool_calls) == 1
        assert "tc-1" in snapshot.tool_calls

    def test_accumulator_tracks_messages(self):
        sc = StreamConsolidator(session_id="ses-acc2")
        sc.process(make_agent_message("hello.\n"))
        sc.process(make_agent_message("world.\n"))
        snapshot = sc.accumulator.snapshot()
        assert len(snapshot.agent_messages) == 2
