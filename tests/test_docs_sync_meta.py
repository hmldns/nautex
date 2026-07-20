"""Unit tests for docs sync metadata (services/docs_meta.py)."""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nautex.services import docs_meta
from nautex.services.docs_meta import (
    CLOCK_SKEW_TOLERANCE,
    LOCK_FILENAME,
    SYNC_META_FILENAME,
    DocMetaEntry,
    DocsSyncMeta,
    RefetchReason,
    needs_refetch,
    parse_iso_utc,
)

LOGGER_NAME = "nautex.services.docs_meta"

NOW = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)
TS_OLD = "2026-07-07T10:00:00+00:00"
TS_NEW = "2026-07-07T11:00:00+00:00"


def make_entry(updated_at=TS_OLD, pulled_at=TS_OLD, path="PRD.md"):
    return DocMetaEntry(updated_at=updated_at, pulled_at=pulled_at, path=path)


# ---------------------------------------------------------------------------
# parse_iso_utc
# ---------------------------------------------------------------------------

class TestParseIsoUtc:
    def test_offset_form(self):
        assert parse_iso_utc("2026-07-07T10:00:00+00:00") == datetime(
            2026, 7, 7, 10, 0, 0, tzinfo=timezone.utc)

    def test_non_utc_offset_normalized(self):
        assert parse_iso_utc("2026-07-07T12:00:00+02:00") == datetime(
            2026, 7, 7, 10, 0, 0, tzinfo=timezone.utc)

    def test_z_suffix(self):
        # Python 3.10 fromisoformat can't parse 'Z' natively — must be handled.
        assert parse_iso_utc("2026-07-07T10:00:00Z") == datetime(
            2026, 7, 7, 10, 0, 0, tzinfo=timezone.utc)

    def test_naive_assumed_utc_with_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            result = parse_iso_utc("2026-07-07T10:00:00")
        assert result == datetime(2026, 7, 7, 10, 0, 0, tzinfo=timezone.utc)
        assert "assuming UTC" in caplog.text

    def test_garbage_returns_none_with_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            assert parse_iso_utc("not-a-timestamp") is None
        assert "Malformed timestamp" in caplog.text

    def test_none_and_empty(self):
        assert parse_iso_utc(None) is None
        assert parse_iso_utc("") is None


# ---------------------------------------------------------------------------
# needs_refetch — one test per decision-table rule
# ---------------------------------------------------------------------------

class TestNeedsRefetch:
    @pytest.fixture
    def local_file(self, tmp_path):
        f = tmp_path / "PRD.md"
        f.write_text("# doc")
        return f

    def test_rule1_no_server_ts(self, local_file):
        # Covers both "absent from meta" and "null value" (new document).
        assert needs_refetch(make_entry(), None, local_file, now=NOW) == (True, RefetchReason.NO_SERVER_TS)

    def test_rule2_bad_server_ts(self, local_file):
        assert needs_refetch(make_entry(), "garbage", local_file, now=NOW) == (True, RefetchReason.BAD_SERVER_TS)

    def test_rule3_no_meta_entry(self, local_file):
        assert needs_refetch(None, TS_OLD, local_file, now=NOW) == (True, RefetchReason.NO_META_ENTRY)

    def test_rule4_stored_ts_missing(self, local_file):
        entry = make_entry(updated_at=None)
        assert needs_refetch(entry, TS_OLD, local_file, now=NOW) == (True, RefetchReason.BAD_STORED_TS)

    def test_rule4_stored_ts_malformed(self, local_file):
        entry = make_entry(updated_at="garbage")
        assert needs_refetch(entry, TS_OLD, local_file, now=NOW) == (True, RefetchReason.BAD_STORED_TS)

    def test_rule5_stored_ts_in_future(self, local_file):
        future = (NOW + CLOCK_SKEW_TOLERANCE + timedelta(minutes=1)).isoformat()
        entry = make_entry(updated_at=future)
        assert needs_refetch(entry, TS_OLD, local_file, now=NOW) == (True, RefetchReason.STORED_TS_IN_FUTURE)

    def test_rule5_within_skew_tolerance_not_future(self, local_file):
        near_future = (NOW + CLOCK_SKEW_TOLERANCE - timedelta(minutes=1)).isoformat()
        entry = make_entry(updated_at=near_future)
        assert needs_refetch(entry, TS_OLD, local_file, now=NOW) == (False, RefetchReason.UP_TO_DATE)

    def test_rule6_local_file_missing(self, tmp_path):
        missing = tmp_path / "PRD.md"
        entry = make_entry()
        assert needs_refetch(entry, TS_OLD, missing, now=NOW) == (True, RefetchReason.LOCAL_FILE_MISSING)

    def test_rule7_server_newer(self, local_file):
        entry = make_entry(updated_at=TS_OLD)
        assert needs_refetch(entry, TS_NEW, local_file, now=NOW) == (True, RefetchReason.SERVER_NEWER)

    def test_rule8_up_to_date_equal(self, local_file):
        entry = make_entry(updated_at=TS_OLD)
        assert needs_refetch(entry, TS_OLD, local_file, now=NOW) == (False, RefetchReason.UP_TO_DATE)

    def test_rule8_up_to_date_server_older(self, local_file):
        entry = make_entry(updated_at=TS_NEW)
        assert needs_refetch(entry, TS_OLD, local_file, now=NOW) == (False, RefetchReason.UP_TO_DATE)


# ---------------------------------------------------------------------------
# DocsSyncMeta load/save
# ---------------------------------------------------------------------------

class TestLoadSave:
    def test_load_missing_file(self, tmp_path):
        meta = DocsSyncMeta.load(tmp_path)
        assert meta.entries == {}

    def test_load_malformed_json(self, tmp_path, caplog):
        (tmp_path / SYNC_META_FILENAME).write_text("{not json")
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            meta = DocsSyncMeta.load(tmp_path)
        assert meta.entries == {}
        assert "Invalid docs sync metadata" in caplog.text

    def test_load_wrong_schema_version(self, tmp_path, caplog):
        (tmp_path / SYNC_META_FILENAME).write_text(
            json.dumps({"schema_version": 99, "documents": {"PRD": {}}}))
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            meta = DocsSyncMeta.load(tmp_path)
        assert meta.entries == {}
        assert "schema" in caplog.text

    def test_load_skips_invalid_entry(self, tmp_path):
        (tmp_path / SYNC_META_FILENAME).write_text(json.dumps({
            "schema_version": 1,
            "documents": {
                "PRD": {"updated_at": TS_OLD, "pulled_at": TS_OLD, "path": "PRD.md"},
                "BAD": "not-a-dict",
            },
        }))
        meta = DocsSyncMeta.load(tmp_path)
        assert set(meta.entries) == {"PRD"}

    def test_save_load_roundtrip(self, tmp_path):
        meta = DocsSyncMeta.load(tmp_path)
        meta.record_sync("PRD", updated_at=TS_OLD, path="PRD.md")
        meta.save()

        reloaded = DocsSyncMeta.load(tmp_path)
        entry = reloaded.get("PRD")
        assert entry is not None
        assert entry.updated_at == TS_OLD
        assert entry.path == "PRD.md"
        assert parse_iso_utc(entry.pulled_at) is not None

    def test_record_sync_null_updated_at_roundtrip(self, tmp_path):
        meta = DocsSyncMeta.load(tmp_path)
        meta.record_sync("NEW", updated_at=None, path="NEW.md")
        meta.save()
        assert DocsSyncMeta.load(tmp_path).get("NEW").updated_at is None

    def test_save_failure_never_raises(self, tmp_path, monkeypatch, caplog):
        meta = DocsSyncMeta.load(tmp_path)
        meta.record_sync("PRD", updated_at=TS_OLD, path="PRD.md")
        monkeypatch.setattr(os, "replace", _raise_os_error)
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            meta.save()  # must not raise
        assert "Failed to save docs sync metadata" in caplog.text


def _raise_os_error(*args, **kwargs):
    raise OSError("disk full")


# ---------------------------------------------------------------------------
# Merge-on-save (concurrent writers)
# ---------------------------------------------------------------------------

class TestMergeOnSave:
    def test_other_process_entry_survives(self, tmp_path):
        ours = DocsSyncMeta.load(tmp_path)
        ours.record_sync("PRD", updated_at=TS_OLD, path="PRD.md")

        # "Another process" syncs a different doc between our load and save.
        other = DocsSyncMeta.load(tmp_path)
        other.record_sync("TRD", updated_at=TS_NEW, path="TRD.md")
        other.save()

        ours.save()
        reloaded = DocsSyncMeta.load(tmp_path)
        assert set(reloaded.entries) == {"PRD", "TRD"}

    def test_newer_disk_entry_wins_conflict(self, tmp_path):
        ours = DocsSyncMeta(tmp_path)
        ours.entries["PRD"] = make_entry(updated_at=TS_OLD, pulled_at=TS_OLD)

        newer = DocsSyncMeta(tmp_path)
        newer.entries["PRD"] = make_entry(updated_at=TS_NEW, pulled_at=TS_NEW)
        newer.save()

        ours.save()
        assert DocsSyncMeta.load(tmp_path).get("PRD").updated_at == TS_NEW

    def test_our_entry_wins_over_older_disk(self, tmp_path):
        older = DocsSyncMeta(tmp_path)
        older.entries["PRD"] = make_entry(updated_at=TS_OLD, pulled_at=TS_OLD)
        older.save()

        ours = DocsSyncMeta(tmp_path)
        ours.entries["PRD"] = make_entry(updated_at=TS_NEW, pulled_at=TS_NEW)
        ours.save()
        assert DocsSyncMeta.load(tmp_path).get("PRD").updated_at == TS_NEW


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------

class TestLocking:
    def test_lock_released_after_save(self, tmp_path):
        meta = DocsSyncMeta.load(tmp_path)
        meta.record_sync("PRD", updated_at=TS_OLD, path="PRD.md")
        meta.save()
        assert not (tmp_path / LOCK_FILENAME).exists()
        assert (tmp_path / SYNC_META_FILENAME).exists()

    def test_fresh_lock_times_out_and_degrades(self, tmp_path, monkeypatch, caplog):
        (tmp_path / LOCK_FILENAME).write_text("12345\n")
        monkeypatch.setattr(docs_meta, "LOCK_TIMEOUT", 0.2)

        meta = DocsSyncMeta.load(tmp_path)
        meta.record_sync("PRD", updated_at=TS_OLD, path="PRD.md")
        start = time.monotonic()
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            meta.save()  # must not raise, must still write
        assert time.monotonic() - start >= 0.2
        assert "Timed out waiting for docs sync lock" in caplog.text
        assert DocsSyncMeta.load(tmp_path).get("PRD") is not None
        # The foreign lock is not ours to remove.
        assert (tmp_path / LOCK_FILENAME).exists()

    def test_stale_lock_is_broken(self, tmp_path, caplog):
        lock = tmp_path / LOCK_FILENAME
        lock.write_text("12345\n")
        stale = time.time() - docs_meta.LOCK_STALE_AFTER - 10
        os.utime(lock, (stale, stale))

        meta = DocsSyncMeta.load(tmp_path)
        meta.record_sync("PRD", updated_at=TS_OLD, path="PRD.md")
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            meta.save()
        assert "Breaking stale docs sync lock" in caplog.text
        assert DocsSyncMeta.load(tmp_path).get("PRD") is not None
        assert not lock.exists()


# ---------------------------------------------------------------------------
# Gitignore handling
# ---------------------------------------------------------------------------

class TestGitignore:
    def test_default_layout_adds_entries(self, tmp_path):
        docs_dir = tmp_path / ".nautex" / "docs"
        meta = DocsSyncMeta(docs_dir)
        meta.record_sync("PRD", updated_at=TS_OLD, path="PRD.md")
        meta.save()

        gitignore = tmp_path / ".nautex" / ".gitignore"
        lines = gitignore.read_text().splitlines()
        assert f"docs/{SYNC_META_FILENAME}" in lines
        assert f"docs/{LOCK_FILENAME}" in lines

    def test_idempotent(self, tmp_path):
        docs_dir = tmp_path / ".nautex" / "docs"
        meta = DocsSyncMeta(docs_dir)
        meta.record_sync("PRD", updated_at=TS_OLD, path="PRD.md")
        meta.save()
        meta.save()

        lines = (tmp_path / ".nautex" / ".gitignore").read_text().splitlines()
        assert lines.count(f"docs/{SYNC_META_FILENAME}") == 1
        assert lines.count(f"docs/{LOCK_FILENAME}") == 1

    def test_preserves_existing_lines(self, tmp_path):
        nautex_dir = tmp_path / ".nautex"
        nautex_dir.mkdir()
        (nautex_dir / ".gitignore").write_text(".env\n")

        meta = DocsSyncMeta(nautex_dir / "docs")
        meta.record_sync("PRD", updated_at=TS_OLD, path="PRD.md")
        meta.save()

        lines = (nautex_dir / ".gitignore").read_text().splitlines()
        assert ".env" in lines
        assert f"docs/{SYNC_META_FILENAME}" in lines

    def test_custom_docs_dir_skipped(self, tmp_path):
        docs_dir = tmp_path / "custom_docs"
        meta = DocsSyncMeta(docs_dir)
        meta.record_sync("PRD", updated_at=TS_OLD, path="PRD.md")
        meta.save()

        assert not (tmp_path / ".gitignore").exists()
        assert not (docs_dir / ".gitignore").exists()
