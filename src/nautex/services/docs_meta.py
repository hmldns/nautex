"""Docs sync metadata — per-document last-update timestamps for dependency docs.

Manages `.nautex/docs/.sync_meta.json`, which records the server-authoritative
`updated_at` timestamp of each dependency document at the time it was last
pulled. `DocumentService.ensure_documents` consults it (via `needs_refetch`)
to skip re-downloading documents that haven't changed on the backend.

Robustness contract: nothing in this module may break the scope flow. A
missing/corrupt metafile, malformed timestamps, or IO failures all degrade to
"re-fetch the document" (the pre-metafile behavior) with a logged warning.
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

SYNC_META_FILENAME = ".sync_meta.json"
LOCK_FILENAME = ".sync_meta.lock"
SCHEMA_VERSION = 1

# Stored timestamps beyond now + tolerance are treated as invalid ("docs must
# never be from the future") and force a re-fetch.
CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)

LOCK_TIMEOUT = 2.0          # seconds to wait for the lock before degrading
LOCK_STALE_AFTER = 30.0     # a lock file older than this is broken (dead process)
LOCK_RETRY_INTERVAL = 0.05


def parse_iso_utc(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp into a tz-aware UTC datetime.

    Handles a trailing 'Z' (Python 3.10 fromisoformat can't). Naive datetimes
    are assumed UTC with a warning — treating them as invalid would silently
    regress to permanent full re-fetch if the backend ever drops the offset.
    Returns None for missing or malformed input.
    """
    if not value or not isinstance(value, str):
        return None
    raw = value.strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        logger.warning("Malformed timestamp %r in docs sync metadata", value)
        return None
    if dt.tzinfo is None:
        logger.warning("Naive timestamp %r in docs sync metadata — assuming UTC", value)
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class DocMetaEntry:
    updated_at: Optional[str]   # server-authoritative, raw string as received
    pulled_at: Optional[str]    # when we wrote the doc locally; informational + merge tiebreak
    path: str                   # filename within the docs dir, e.g. "PRD.md"

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {"updated_at": self.updated_at, "pulled_at": self.pulled_at, "path": self.path}


class RefetchReason(str, Enum):
    """Why needs_refetch decided to fetch — or, for UP_TO_DATE, to skip."""
    NO_SERVER_TS = "no_server_ts"           # designator absent from server meta or null ts (new doc)
    BAD_SERVER_TS = "bad_server_ts"
    NO_META_ENTRY = "no_meta_entry"         # never synced
    BAD_STORED_TS = "bad_stored_ts"
    STORED_TS_IN_FUTURE = "stored_ts_in_future"
    LOCAL_FILE_MISSING = "local_file_missing"
    LOCAL_FILE_EMPTY = "local_file_empty"
    SERVER_NEWER = "server_newer"
    UP_TO_DATE = "up_to_date"               # the only non-fetch outcome


def needs_refetch(
    entry: Optional[DocMetaEntry],
    server_ts_raw: Optional[str],
    local_file: Path,
    now: Optional[datetime] = None,
) -> Tuple[bool, RefetchReason]:
    """Decide whether a dependency document must be re-fetched.

    Returns (decision, reason). Every uncertain case resolves to re-fetch.
    """
    if server_ts_raw is None:
        return True, RefetchReason.NO_SERVER_TS
    server_dt = parse_iso_utc(server_ts_raw)
    if server_dt is None:
        return True, RefetchReason.BAD_SERVER_TS
    if entry is None:
        return True, RefetchReason.NO_META_ENTRY
    stored_dt = parse_iso_utc(entry.updated_at)
    if stored_dt is None:
        return True, RefetchReason.BAD_STORED_TS
    if now is None:
        now = datetime.now(timezone.utc)
    if stored_dt > now + CLOCK_SKEW_TOLERANCE:
        return True, RefetchReason.STORED_TS_IN_FUTURE
    if not local_file.exists():
        return True, RefetchReason.LOCAL_FILE_MISSING
    try:
        if local_file.stat().st_size == 0:
            return True, RefetchReason.LOCAL_FILE_EMPTY
    except OSError:
        return True, RefetchReason.LOCAL_FILE_MISSING
    if server_dt > stored_dt:
        return True, RefetchReason.SERVER_NEWER
    return False, RefetchReason.UP_TO_DATE


class DocsSyncMeta:
    """Load/record/save the per-document sync metadata for a docs directory."""

    def __init__(self, docs_dir: Path, entries: Optional[Dict[str, DocMetaEntry]] = None):
        self.docs_dir = Path(docs_dir)
        self.entries: Dict[str, DocMetaEntry] = dict(entries or {})

    @property
    def path(self) -> Path:
        return self.docs_dir / SYNC_META_FILENAME

    @classmethod
    def load(cls, docs_dir: Path) -> "DocsSyncMeta":
        """Read the metafile. Never raises — invalid file yields empty metadata."""
        meta = cls(docs_dir)
        meta.entries = _read_entries(meta.path)
        return meta

    def get(self, designator: str) -> Optional[DocMetaEntry]:
        return self.entries.get(designator)

    def record_sync(self, designator: str, updated_at: Optional[str], path: str) -> None:
        self.entries[designator] = DocMetaEntry(
            updated_at=updated_at,
            pulled_at=datetime.now(timezone.utc).isoformat(),
            path=path,
        )

    def save(self) -> None:
        """Persist entries, merging with concurrent writers. Never raises.

        Under the lock, re-reads the file and merges our entries on top
        (per designator, newest pulled_at wins) so a concurrent MCP/CLI/gateway
        sync can't lose updates; the write itself is tmp-file + os.replace.
        """
        try:
            self.docs_dir.mkdir(parents=True, exist_ok=True)
            with _meta_lock(self.docs_dir):
                merged = _merge_entries(_read_entries(self.path), self.entries)
                payload = {
                    "schema_version": SCHEMA_VERSION,
                    "documents": {d: e.to_dict() for d, e in merged.items()},
                }
                tmp = self.path.parent / (self.path.name + ".tmp")
                tmp.write_text(json.dumps(payload, indent=2) + "\n")
                os.replace(tmp, self.path)
                self.entries = merged
            _ensure_metafile_gitignored(self.docs_dir)
        except Exception as e:
            logger.warning("Failed to save docs sync metadata %s: %s", self.path, e)


def _read_entries(path: Path) -> Dict[str, DocMetaEntry]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        if data.get("schema_version") != SCHEMA_VERSION:
            logger.warning(
                "Unsupported docs sync metadata schema in %s: %r",
                path, data.get("schema_version"),
            )
            return {}
        entries: Dict[str, DocMetaEntry] = {}
        for designator, value in data.get("documents", {}).items():
            if not isinstance(value, dict):
                logger.warning("Skipping invalid docs sync metadata entry %r in %s", designator, path)
                continue
            entries[designator] = DocMetaEntry(
                updated_at=value.get("updated_at"),
                pulled_at=value.get("pulled_at"),
                path=value.get("path") or f"{designator}.md",
            )
        return entries
    except (json.JSONDecodeError, AttributeError, TypeError, KeyError) as e:
        logger.warning("Invalid docs sync metadata file %s: %s", path, e)
        return {}


def _merge_entries(
    on_disk: Dict[str, DocMetaEntry],
    ours: Dict[str, DocMetaEntry],
) -> Dict[str, DocMetaEntry]:
    merged = dict(on_disk)
    for designator, entry in ours.items():
        existing = merged.get(designator)
        if existing is None or not _pulled_strictly_later(existing, entry):
            merged[designator] = entry
    return merged


def _pulled_strictly_later(a: DocMetaEntry, b: DocMetaEntry) -> bool:
    a_dt = parse_iso_utc(a.pulled_at)
    b_dt = parse_iso_utc(b.pulled_at)
    if a_dt is None:
        return False
    if b_dt is None:
        return True
    return a_dt > b_dt


@contextmanager
def _meta_lock(docs_dir: Path):
    """Best-effort lock around the metafile read-merge-write critical section.

    Waits up to LOCK_TIMEOUT, breaks locks older than LOCK_STALE_AFTER, and on
    timeout or IO error proceeds WITHOUT the lock (warning) — the scope flow
    must never block or crash on lock contention.
    """
    lock_path = docs_dir / LOCK_FILENAME
    acquired = False
    deadline = time.monotonic() + LOCK_TIMEOUT
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, f"{os.getpid()}\n".encode())
            finally:
                os.close(fd)
            acquired = True
            break
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except OSError:
                continue  # lock vanished between open and stat — retry
            if age > LOCK_STALE_AFTER:
                logger.warning("Breaking stale docs sync lock %s (age %.0fs)", lock_path, age)
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                continue
            if time.monotonic() >= deadline:
                logger.warning(
                    "Timed out waiting for docs sync lock %s — proceeding without it", lock_path,
                )
                break
            time.sleep(LOCK_RETRY_INTERVAL)
        except OSError as e:
            logger.warning("Cannot create docs sync lock %s: %s — proceeding without it", lock_path, e)
            break
    try:
        yield
    finally:
        if acquired:
            try:
                lock_path.unlink()
            except OSError:
                pass


def _ensure_metafile_gitignored(docs_dir: Path) -> None:
    """Ensure the docs folder's own .gitignore covers the sync metafile and lock.

    Nautex owns the docs folder, so the .gitignore lives right inside it —
    this works for any docs location, default or custom. Existing content is
    preserved; only missing lines are appended.
    """
    try:
        gitignore = docs_dir / ".gitignore"
        for line in (SYNC_META_FILENAME, LOCK_FILENAME):
            _ensure_gitignored_line(gitignore, line)
    except Exception as e:
        logger.warning("Failed to update docs .gitignore for sync metadata: %s", e)


def _ensure_gitignored_line(gitignore: Path, line: str) -> None:
    if gitignore.exists():
        content = gitignore.read_text()
        if line in content.splitlines():
            return
        gitignore.write_text(content.rstrip("\n") + "\n" + line + "\n")
    else:
        gitignore.write_text(line + "\n")
