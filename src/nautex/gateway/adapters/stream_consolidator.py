"""Stream consolidator — buffers raw ACP session updates into semantic objects.

Wraps the SDK's SessionAccumulator to accumulate ACP SessionNotification
objects and maps them to ConsolidatedSessionUpdate at semantic boundaries.

Text chunks (agent_message_chunk, agent_thought_chunk) are buffered until
a sentence boundary is detected (sentence-ending punctuation, newline,
double newline) or a non-text update flushes the buffer. This prevents
single-word chunk spam on the channel.

Responsibilities:
- Validate incoming payloads via strict Pydantic validation (MDS-36)
- Buffer via SDK SessionAccumulator (MDS-86)
- Semantic batching of text streams at sentence boundaries (MDS-81)
- Map ACP update types → ConsolidatedSessionUpdate.kind (MDS-81)
- Extract telemetry counters for 3Hz pulse (MDS-82)
- Deduplicate replay storms from session/load (MDS-85)

Reference: MDS-36, MDS-81, MDS-82, MDS-85, MDS-86
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from acp.contrib.session_state import SessionAccumulator
from acp.schema import SessionNotification

from ..models import ConsolidatedSessionUpdate
from ..telemetry import EphemeralSessionTelemetry

logger = logging.getLogger(__name__)

# Text kinds that get buffered for sentence-boundary batching
_TEXT_KINDS = frozenset({"agent_message_chunk", "agent_thought_chunk"})

# Sentence-ending patterns that trigger a flush
_SENTENCE_ENDINGS = (".\n", "!\n", "?\n", "\n\n", ".\r\n")
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

        # Text buffering — accumulate chunks until sentence boundary
        self._text_buffer = ""
        self._text_buffer_kind: Optional[str] = None

        # Telemetry counters — sampled at 3Hz by the gateway service
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
        """Mark current position for replay deduplication.

        Call before session/load to record how many updates have been
        processed. The next N updates (where N = current total) will be
        suppressed as replayed history.
        """
        self._replay_skip_remaining = self._total_updates

    def stop_replay(self) -> None:
        """Clear replay deduplication state."""
        self._replay_skip_remaining = 0

    def process(self, raw_update: Any) -> List[ConsolidatedSessionUpdate]:
        """Validate and consolidate a raw ACP session update.

        Returns a list of ConsolidatedSessionUpdate objects. Usually 0 or 1,
        but can be 2 when a non-text update flushes a pending text buffer.

        Text chunks are buffered until a sentence boundary. Non-text updates
        flush the buffer first, then emit themselves.

        Args:
            raw_update: The update object from the SDK's session_update callback.

        Returns:
            List of ConsolidatedSessionUpdate objects ready for emission.

        Raises:
            ProtocolParseError: If the update cannot be validated.
        """
        try:
            kind = self._extract_kind(raw_update)
            data = self._extract_data(raw_update, kind)
        except Exception as e:
            raise ProtocolParseError(
                f"Failed to parse ACP session update: {e}"
            ) from e

        self._total_updates += 1

        # Replay deduplication — suppress replayed updates (MDS-85)
        if self._replay_skip_remaining > 0:
            self._replay_skip_remaining -= 1
            return [ConsolidatedSessionUpdate(
                kind="replay_skip",
                data={"original_kind": kind},
                session_id=self._session_id,
            )]

        # Feed SDK accumulator
        try:
            notif = SessionNotification(
                session_id=self._session_id, update=raw_update
            )
            self._accumulator.apply(notif)
        except Exception as e:
            logger.debug("SessionAccumulator.apply failed: %s", e)

        # Update telemetry counters
        self._update_telemetry(kind, data)

        # Text kinds: buffer and batch at sentence boundaries (if enabled)
        if kind in _TEXT_KINDS:
            if self._buffer_text:
                return self._buffer_text_chunk(kind, data)
            # No buffering — emit each chunk immediately
            csu = ConsolidatedSessionUpdate(
                kind=kind, data=data, session_id=self._session_id,
            )
            self._updates.append(csu)
            return [csu]

        # Non-text: flush any pending text buffer, then emit this update
        result = self._flush_text_buffer()

        csu = ConsolidatedSessionUpdate(
            kind=kind,
            data=data,
            session_id=self._session_id,
        )
        self._updates.append(csu)
        result.append(csu)
        return result

    def flush(self) -> List[ConsolidatedSessionUpdate]:
        """Flush any remaining buffered text. Call at end of stream."""
        return self._flush_text_buffer()

    def get_telemetry(self) -> EphemeralSessionTelemetry:
        """Sample current telemetry state for 3Hz pulse."""
        return EphemeralSessionTelemetry(
            session_id=self._session_id,
            active_tool=self._active_tool,
            processed_tokens_estimate=self._word_count,
            is_typing=self._is_typing,
        )

    @property
    def update_count(self) -> int:
        """Total consolidated updates produced (excluding replay skips)."""
        return len(self._updates)

    @property
    def accumulator(self) -> SessionAccumulator:
        """Access the underlying SDK accumulator for snapshot queries."""
        return self._accumulator

    # ------------------------------------------------------------------
    # Text buffering
    # ------------------------------------------------------------------

    def _buffer_text_chunk(self, kind: str, data: Dict[str, Any]) -> List[ConsolidatedSessionUpdate]:
        """Buffer a text chunk. Emit when sentence boundary is reached."""
        text = data.get("text", "")

        # If kind changed (thought → message or vice versa), flush first
        result: List[ConsolidatedSessionUpdate] = []
        if self._text_buffer_kind and self._text_buffer_kind != kind:
            result = self._flush_text_buffer()

        self._text_buffer += text
        self._text_buffer_kind = kind

        # Check for sentence boundary
        if self._has_sentence_boundary():
            result.extend(self._flush_text_buffer())

        return result

    def _has_sentence_boundary(self) -> bool:
        """Check if buffered text ends at a sentence boundary."""
        buf = self._text_buffer
        if not buf:
            return False

        # Double newline — paragraph break
        if buf.endswith("\n\n"):
            return True

        # Single newline at end
        if buf.endswith("\n"):
            return True

        # Sentence-ending punctuation followed by space or at end
        stripped = buf.rstrip()
        if stripped and stripped[-1] in _SENTENCE_TERMINATORS:
            return True

        return False

    def _flush_text_buffer(self) -> List[ConsolidatedSessionUpdate]:
        """Flush accumulated text buffer into a CSU. Returns list (0 or 1)."""
        if not self._text_buffer:
            return []

        csu = ConsolidatedSessionUpdate(
            kind=self._text_buffer_kind or "agent_message_chunk",
            data={"text": self._text_buffer},
            session_id=self._session_id,
        )
        self._updates.append(csu)

        self._text_buffer = ""
        self._text_buffer_kind = None
        return [csu]

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_kind(update: Any) -> str:
        """Get the ACP session_update type string.

        Let it crash on missing attribute — contract violation must be visible.
        """
        return str(update.session_update)

    @staticmethod
    def _extract_data(update: Any, kind: str) -> Dict[str, Any]:
        """Extract relevant payload from an ACP update into a dict.

        Uses direct attribute access — no getattr fallbacks.
        Contract violations crash here and propagate as ProtocolParseError.
        """
        data: Dict[str, Any] = {}

        if kind == "agent_message_chunk":
            data["text"] = update.content.text

        elif kind in ("tool_call", "tool_call_update"):
            data["tool_call_id"] = update.tool_call_id
            data["title"] = update.title or ""
            data["status"] = str(update.status) if update.status else ""
            if update.kind:
                data["tool_kind"] = str(update.kind)

        elif kind == "agent_thought_chunk":
            data["text"] = update.content.text

        elif kind == "current_mode_update":
            data["mode_id"] = update.current_mode_id

        elif kind == "available_commands_update":
            data["count"] = len(update.available_commands or [])

        elif kind == "usage_update":
            data["size"] = update.size
            data["used"] = update.used
            if update.cost is not None:
                data["cost"] = update.cost

        return data

    def _update_telemetry(self, kind: str, data: Dict[str, Any]) -> None:
        """Update internal telemetry counters from a processed update."""
        text = data.get("text", "")
        if text:
            self._word_count += len(text.split())
            self._is_typing = True
        elif kind in ("tool_call", "tool_call_update"):
            self._is_typing = False
            status = data.get("status", "")
            if status in ("pending", "in_progress"):
                self._active_tool = data.get("title") or data.get("tool_call_id")
            elif status == "completed":
                self._active_tool = None
        elif kind not in ("available_commands_update", "current_mode_update",
                          "config_option_update", "session_info_update"):
            self._is_typing = False
