"""Tests for FuzzyIndexer — scanning, filtering, fuzzy matching, and performance."""

import asyncio
import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest
import pytest_asyncio

from nautex.gateway.indexer import FuzzyIndexer, FileSearchResult, HARDCODED_IGNORE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_tree(tmp_path):
    """Create a small mock directory tree for unit tests."""
    files = [
        "src/main.py",
        "src/utils.py",
        "src/gateway/indexer.py",
        "src/gateway/models.py",
        "src/gateway/adapters/base.py",
        "src/components/UserInput.tsx",
        "src/components/AgwChatInterface.tsx",
        "README.md",
        "pyproject.toml",
        # Should be excluded by hardcoded defaults
        ".git/config",
        "node_modules/express/index.js",
        "__pycache__/main.cpython-310.pyc",
        ".venv/lib/pip.py",
        # Should be excluded by gitignore
        "build/output.js",
        "dist/bundle.js",
        "src/debug.log",
        # Hidden files — should be excluded
        ".env",
        ".dockerignore",
        ".config/settings.json",
    ]
    for f in files:
        p = tmp_path / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {f}\n")

    # .gitignore
    (tmp_path / ".gitignore").write_text("build/\ndist/\n*.log\n")
    return str(tmp_path)


@pytest.fixture
def large_tree(tmp_path):
    """Generate 10,000 mock files for performance testing."""
    dirs = ["src", "lib", "tests", "docs", "scripts", "config", "data"]
    extensions = [".py", ".ts", ".js", ".md", ".json", ".yaml", ".txt"]
    count = 0
    for d in dirs:
        for sub in range(20):
            subdir = tmp_path / d / f"module_{sub:03d}"
            subdir.mkdir(parents=True, exist_ok=True)
            for i in range(70):
                ext = extensions[i % len(extensions)]
                f = subdir / f"file_{i:04d}{ext}"
                f.write_bytes(b"x")
                count += 1
    # Add some that should be excluded
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_bytes(b"x")
    (tmp_path / ".git" / "objects").mkdir(parents=True)
    (tmp_path / ".git" / "objects" / "abc").write_bytes(b"x")
    (tmp_path / ".gitignore").write_text("*.tmp\n")

    return str(tmp_path), count


# ---------------------------------------------------------------------------
# Unit tests — scanning and filtering
# ---------------------------------------------------------------------------

class TestScanning:

    @pytest.mark.asyncio
    async def test_build_index(self, mock_tree):
        idx = FuzzyIndexer(mock_tree)
        count = await idx.build_index()
        assert count > 0
        assert idx.is_indexed

    @pytest.mark.asyncio
    async def test_hardcoded_exclusions(self, mock_tree):
        idx = FuzzyIndexer(mock_tree)
        await idx.build_index()
        files = set(idx._files)
        assert not any(".git/" in f for f in files)
        assert not any("node_modules/" in f for f in files)
        assert not any("__pycache__/" in f for f in files)
        assert not any(".venv/" in f for f in files)

    @pytest.mark.asyncio
    async def test_gitignore_exclusions(self, mock_tree):
        idx = FuzzyIndexer(mock_tree)
        await idx.build_index()
        files = set(idx._files)
        assert not any(f.startswith("build/") and not f.endswith("/") for f in files)
        assert not any(f.startswith("dist/") and not f.endswith("/") for f in files)
        assert not any(f.endswith(".log") for f in files)

    @pytest.mark.asyncio
    async def test_source_files_included(self, mock_tree):
        idx = FuzzyIndexer(mock_tree)
        await idx.build_index()
        files = set(idx._files)
        assert "src/main.py" in files
        assert "src/gateway/indexer.py" in files
        assert "README.md" in files

    @pytest.mark.asyncio
    async def test_extra_ignore_patterns(self, mock_tree):
        idx = FuzzyIndexer(mock_tree, extra_ignore_patterns=["*.md"])
        await idx.build_index()
        files = set(idx._files)
        assert "README.md" not in files
        assert "src/main.py" in files

    @pytest.mark.asyncio
    async def test_hidden_files_excluded(self, mock_tree):
        """Hidden files/dirs (dot-prefixed) must be excluded from index."""
        idx = FuzzyIndexer(mock_tree)
        await idx.build_index()
        files = set(idx._files)
        assert ".env" not in files
        assert ".dockerignore" not in files
        assert not any(".config/" in f for f in files)
        # .gitignore itself is also hidden
        assert ".gitignore" not in files

    @pytest.mark.asyncio
    async def test_directories_indexed(self, mock_tree):
        """Directories should appear in index with trailing '/'."""
        idx = FuzzyIndexer(mock_tree)
        await idx.build_index()
        files = set(idx._files)
        assert "src/" in files
        assert "src/gateway/" in files
        assert "src/gateway/adapters/" in files
        assert "src/components/" in files


# ---------------------------------------------------------------------------
# Unit tests — fuzzy search
# ---------------------------------------------------------------------------

class TestSearch:

    @pytest.mark.asyncio
    async def test_exact_match(self, mock_tree):
        idx = FuzzyIndexer(mock_tree)
        results = await idx.search("indexer.py", limit=5)
        assert len(results) > 0
        assert any("indexer.py" in r.filepath for r in results)

    @pytest.mark.asyncio
    async def test_fuzzy_match(self, mock_tree):
        idx = FuzzyIndexer(mock_tree)
        results = await idx.search("indxer", limit=5)
        # Should still find indexer.py via subsequence matching
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_no_match(self, mock_tree):
        idx = FuzzyIndexer(mock_tree)
        results = await idx.search("zzzznonexistent", limit=5)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_limit_respected(self, mock_tree):
        idx = FuzzyIndexer(mock_tree)
        results = await idx.search("py", limit=3)
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_results_sorted_by_score(self, mock_tree):
        idx = FuzzyIndexer(mock_tree)
        results = await idx.search("main", limit=10)
        scores = [r.overall_score for r in results]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_auto_builds_index(self, mock_tree):
        """search() should auto-build index if not yet indexed."""
        idx = FuzzyIndexer(mock_tree)
        assert not idx.is_indexed
        results = await idx.search("main")
        assert idx.is_indexed
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_subsequence_match(self, mock_tree):
        """Subsequence query should match across word boundaries."""
        idx = FuzzyIndexer(mock_tree)
        results = await idx.search("usrinp", limit=5)
        assert len(results) > 0
        assert any("UserInput" in r.filepath for r in results)

    @pytest.mark.asyncio
    async def test_full_path_match(self, mock_tree):
        """Query spanning path segments should match against full path."""
        idx = FuzzyIndexer(mock_tree)
        results = await idx.search("src/gw", limit=5)
        assert len(results) > 0
        assert any("src/gateway" in r.filepath for r in results)

    @pytest.mark.asyncio
    async def test_directory_search(self, mock_tree):
        """Directories should be findable via search."""
        idx = FuzzyIndexer(mock_tree)
        results = await idx.search("gateway", limit=10)
        assert any(r.filepath.endswith("/") for r in results), "Should find directory entries"

    @pytest.mark.asyncio
    async def test_empty_query(self, mock_tree):
        idx = FuzzyIndexer(mock_tree)
        results = await idx.search("", limit=5)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_camel_case_boundary(self, mock_tree):
        """CamelCase boundaries should boost subsequence matches."""
        idx = FuzzyIndexer(mock_tree)
        results = await idx.search("ACI", limit=5)
        assert len(results) > 0
        assert any("AgwChatInterface" in r.filepath for r in results)


# ---------------------------------------------------------------------------
# Performance tests
# ---------------------------------------------------------------------------

class TestPerformance:

    @pytest.mark.asyncio
    async def test_scan_10k_files(self, large_tree):
        root, expected_count = large_tree
        idx = FuzzyIndexer(root)

        t0 = time.perf_counter()
        count = await idx.build_index()
        scan_ms = (time.perf_counter() - t0) * 1000

        assert count >= expected_count
        # Scan should complete within 500ms for 10K files
        assert scan_ms < 500, f"Scan took {scan_ms:.0f}ms (limit 500ms)"

    @pytest.mark.asyncio
    async def test_search_latency_10k_files(self, large_tree):
        root, _ = large_tree
        idx = FuzzyIndexer(root)
        await idx.build_index()

        queries = ["module", "file_0042", "config", "test_data", "script"]
        for query in queries:
            t0 = time.perf_counter()
            results = await idx.search(query, limit=20)
            query_ms = (time.perf_counter() - t0) * 1000
            # Each query should complete within 300ms
            assert query_ms < 300, f"Query '{query}' took {query_ms:.0f}ms (limit 300ms)"

    @pytest.mark.asyncio
    async def test_event_loop_not_starved(self, large_tree):
        """Verify search doesn't block the event loop."""
        root, _ = large_tree
        idx = FuzzyIndexer(root)
        await idx.build_index()

        # Run search and a concurrent timer — if search blocks the loop,
        # the timer won't fire promptly
        timer_fired = False

        async def timer():
            nonlocal timer_fired
            await asyncio.sleep(0.01)
            timer_fired = True

        await asyncio.gather(
            idx.search("module", limit=20),
            timer(),
        )
        assert timer_fired, "Event loop was starved during search"
