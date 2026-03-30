"""Stream consolidator — buffers raw ACP session updates into semantic objects.

Wraps the SDK's SessionAccumulator to accumulate ACP SessionNotification
objects and maps them to ConsolidatedSessionUpdate at semantic boundaries.

Text chunks (agent_message_chunk, agent_thought_chunk) are buffered until
a sentence boundary is detected (sentence-ending punctuation, newline,
double newline) or a non-text update flushes the buffer. This prevents
single-word chunk spam on the channel.

Reference: MDS-36, MDS-81, MDS-82, MDS-85, MDS-86
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from acp.contrib.session_state import SessionAccumulator
from acp.schema import SessionNotification

from ..protocol import (
    ConsolidatedSessionUpdate,
    EphemeralSessionTelemetry,
    SessionUpdateKind,
    ToolCallStatus,
    ToolKind,
)

logger = logging.getLogger(__name__)

# Text kinds that get buffered for sentence-boundary batching
_TEXT_KINDS = frozenset({
    SessionUpdateKind.AGENT_MESSAGE,
    SessionUpdateKind.AGENT_THOUGHT,
})

# Sentence-ending patterns that trigger a flush
_SENTENCE_TERMINATORS = frozenset(".!?\n")


class ProtocolParseError(Exception):
    """Raised when an incoming ACP payload fails strict validation.

    The adapter must catch this, set state to CRASHED, and tear down
    the subprocess. Reference: MDS-36
    """
    pass


class StreamConsolidator:
    """Buffers raw ACP session updates into ConsolidatedSessionUpdate objects.

    Text chunks are accumulated until a sentence boundary is reached.
    Non-text updates are emitted immediately, flushing any pending text first.

    Telemetry counters (word count, active tool) are tracked independently
    and can be sampled at 3Hz via get_telemetry().
    """

    def __init__(self, session_id: str, buffer_text: bool = True):
        self._session_id = session_id
        self._buffer_text = buffer_text
        self._accumulator = SessionAccumulator()
        self._updates: List[ConsolidatedSessionUpdate] = []

        # Text buffering with time-based throttle
        self._text_parts: List[str] = []    # list append, not string concat
        self._text_buffer_kind: Optional[SessionUpdateKind] = None
        self._text_buffer_message_id: Optional[str] = None
        self._last_flush_time: float = 0.0
        self._flush_interval: float = 0.5  # minimum seconds between flushes

        # Telemetry counters
        self._word_count = 0
        self._active_tool: Optional[str] = None
        self._is_typing = False

        # Replay deduplication (MDS-85)
        self._total_updates = 0
        self._replay_skip_remaining = 0

    @property
    def session_id(self) -> str:
        return self._session_id

    def start_replay(self) -> None:
        """Mark current position for replay deduplication."""
        self._replay_skip_remaining = self._total_updates

    def stop_replay(self) -> None:
        self._replay_skip_remaining = 0

    def process(self, raw_update: Any) -> List[ConsolidatedSessionUpdate]:
        """Validate and consolidate a raw ACP session update.

        Returns a list of ConsolidatedSessionUpdate objects. Usually 0 or 1,
        but can be 2 when a non-text update flushes a pending text buffer.

        Raises:
            ProtocolParseError: If the update cannot be validated.
        """
        try:
            kind = self._extract_kind(raw_update)
            logger.info("RAW ACP: kind=%s type=%s", kind.value, type(raw_update).__name__)
            csu = self._build_csu(raw_update, kind)
            csu.acp_session_id = self._session_id
        except Exception as e:
            raise ProtocolParseError(
                f"Failed to parse ACP session update: {e}"
            ) from e

        self._total_updates += 1

        # Replay deduplication (MDS-85)
        if self._replay_skip_remaining > 0:
            self._replay_skip_remaining -= 1
            return [ConsolidatedSessionUpdate(
                kind=SessionUpdateKind.SESSION_INFO,
                acp_session_id=self._session_id,
            )]

        # Feed SDK accumulator
        try:
            notif = SessionNotification(
                session_id=self._session_id, update=raw_update
            )
            self._accumulator.apply(notif)
        except Exception as e:
            logger.debug("SessionAccumulator.apply failed: %s", e)

        # Update telemetry
        self._update_telemetry(csu)

        # Text kinds: buffer at sentence boundaries (if enabled)
        if kind in _TEXT_KINDS:
            if self._buffer_text:
                return self._buffer_text_chunk(csu)
            self._updates.append(csu)
            return [csu]

        # Non-text: flush pending text (message boundary), then emit
        result = self._flush_text_buffer(reset_identity=True)
        self._last_flush_time = time.monotonic()
        self._updates.append(csu)
        result.append(csu)
        return result

    def flush(self) -> List[ConsolidatedSessionUpdate]:
        """Flush any remaining buffered text. Call at end of stream."""
        return self._flush_text_buffer(reset_identity=True)

    def get_telemetry(self) -> EphemeralSessionTelemetry:
        return EphemeralSessionTelemetry(
            acp_session_id=self._session_id,
            active_tool=self._active_tool,
            processed_tokens_estimate=self._word_count,
            is_typing=self._is_typing,
        )

    @property
    def update_count(self) -> int:
        return len(self._updates)

    @property
    def accumulator(self) -> SessionAccumulator:
        return self._accumulator

    # ------------------------------------------------------------------
    # Text buffering
    # ------------------------------------------------------------------

    def _buffer_text_chunk(self, csu: ConsolidatedSessionUpdate) -> List[ConsolidatedSessionUpdate]:
        result: List[ConsolidatedSessionUpdate] = []
        # Flush if kind changed or acp_message_id changed (different logical message)
        if self._text_buffer_kind and (
            self._text_buffer_kind != csu.kind
            or (csu.acp_message_id and self._text_buffer_message_id and csu.acp_message_id != self._text_buffer_message_id)
        ):
            result = self._flush_text_buffer(reset_identity=True)

        # Assign message_id only when starting a new logical message
        if not self._text_buffer_message_id:
            self._text_buffer_message_id = csu.acp_message_id or str(uuid4())

        if csu.text:
            self._text_parts.append(csu.text)
        self._text_buffer_kind = csu.kind

        # Time-throttled flush: only flush on sentence boundary if enough time has passed
        now = time.monotonic()
        if self._has_sentence_boundary() and (now - self._last_flush_time) >= self._flush_interval:
            result.extend(self._flush_text_buffer())
            self._last_flush_time = now
        return result

    def _has_sentence_boundary(self) -> bool:
        if not self._text_parts:
            return False
        last = self._text_parts[-1]
        if not last:
            return False
        if last.endswith("\n\n") or last.endswith("\n"):
            return True
        stripped = last.rstrip()
        if stripped and stripped[-1] in _SENTENCE_TERMINATORS:
            return True
        return False

    def _flush_text_buffer(self, reset_identity: bool = False) -> List[ConsolidatedSessionUpdate]:
        if not self._text_parts:
            if reset_identity:
                self._text_buffer_message_id = None
                self._text_buffer_kind = None
            return []
        text = "".join(self._text_parts)
        csu = ConsolidatedSessionUpdate(
            kind=self._text_buffer_kind or SessionUpdateKind.AGENT_MESSAGE,
            text=text,
            acp_session_id=self._session_id,
            acp_message_id=self._text_buffer_message_id,
        )
        self._updates.append(csu)
        self._text_parts.clear()
        if reset_identity:
            # Message boundary — next text chunk is a new logical message.
            self._text_buffer_message_id = None
            self._text_buffer_kind = None
        return [csu]

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_kind(update: Any) -> SessionUpdateKind:
        return SessionUpdateKind(str(update.session_update))

    @staticmethod
    def _build_csu(update: Any, kind: SessionUpdateKind) -> ConsolidatedSessionUpdate:
        """Build a typed ConsolidatedSessionUpdate from a raw ACP update."""
        if kind in (SessionUpdateKind.AGENT_MESSAGE, SessionUpdateKind.AGENT_THOUGHT):
            return ConsolidatedSessionUpdate(
                kind=kind,
                text=update.content.text,
                acp_message_id=getattr(update, "message_id", None),
            )

        if kind in (SessionUpdateKind.TOOL_CALL, SessionUpdateKind.TOOL_CALL_UPDATE):
            tool_kind = None
            if update.kind:
                try:
                    tool_kind = ToolKind(str(update.kind))
                except ValueError:
                    pass
            status = None
            if update.status:
                try:
                    status = ToolCallStatus(str(update.status))
                except ValueError:
                    pass
            raw_output = getattr(update, "raw_output", None)
            content = getattr(update, "content", None)
            logger.info(
                "CSU %s: id=%s status=%s title=%s kind=%s raw_output=%s content_len=%s",
                kind.value, update.tool_call_id, status, update.title, tool_kind,
                str(raw_output)[:1000] if raw_output else None,
                len(content) if content else 0,
            )
            return ConsolidatedSessionUpdate(
                kind=kind,
                tool_call_id=update.tool_call_id,
                tool_title=update.title or "",
                tool_status=status,
                tool_kind=tool_kind,
            )

        if kind == SessionUpdateKind.CURRENT_MODE:
            return ConsolidatedSessionUpdate(
                kind=kind,
                mode_id=update.current_mode_id,
            )

        if kind == SessionUpdateKind.AVAILABLE_COMMANDS:
            return ConsolidatedSessionUpdate(
                kind=kind,
                commands_count=len(update.available_commands or []),
            )

        if kind == SessionUpdateKind.USAGE:
            return ConsolidatedSessionUpdate(
                kind=kind,
                usage_size=update.size,
                usage_used=update.used,
            )

        if kind == SessionUpdateKind.SESSION_INFO:
            return ConsolidatedSessionUpdate(
                kind=kind,
                session_title=getattr(update, "title", None),
            )

        # CONFIG_OPTION, etc.
        return ConsolidatedSessionUpdate(kind=kind)

    def _update_telemetry(self, csu: ConsolidatedSessionUpdate) -> None:
        if csu.text:
            self._word_count += len(csu.text.split())
            self._is_typing = True
        elif csu.kind in (SessionUpdateKind.TOOL_CALL, SessionUpdateKind.TOOL_CALL_UPDATE):
            self._is_typing = False
            if csu.tool_status in (ToolCallStatus.PENDING, ToolCallStatus.IN_PROGRESS):
                self._active_tool = csu.tool_title or csu.tool_call_id
            elif csu.tool_status == ToolCallStatus.COMPLETED:
                self._active_tool = None
        elif csu.kind not in (SessionUpdateKind.AVAILABLE_COMMANDS,
                              SessionUpdateKind.CURRENT_MODE,
                              SessionUpdateKind.CONFIG_OPTION,
                              SessionUpdateKind.SESSION_INFO):
            self._is_typing = False
