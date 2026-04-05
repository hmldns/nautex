"""Benchmark and correctness tests for search strategies.

Compares all four strategies (Python subsequence, LCSseq hybrid, regex, pure LCSseq)
on the same queries to evaluate correctness, ranking quality, and performance.
"""

import time
from typing import List

import pytest

from nautex.gateway.indexer import (
    FuzzyIndexer,
    FileSearchResult,
    _strategy_python_subsequence,
    _strategy_lcsseq_hybrid,
    _strategy_regex,
    _strategy_lcsseq_pure,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

STRATEGIES = {
    "python_subseq": _strategy_python_subsequence,
    "lcsseq_hybrid": _strategy_lcsseq_hybrid,
    "regex": _strategy_regex,
    "lcsseq_pure": _strategy_lcsseq_pure,
}

# Strategies that guarantee true subsequence matching (not approximate)
SUBSEQUENCE_STRATEGIES = {"python_subseq", "lcsseq_hybrid", "regex"}


@pytest.fixture
def search_tree(tmp_path):
    """Directory tree designed to test subsequence matching edge cases."""
    files = [
        # CamelCase files
        "lib/processing/DataTransformer.py",
        "lib/processing/DataValidatorEngine.py",
        "lib/network/HttpClientPool.py",
        "lib/network/WebSocketHandler.py",
        # Nested paths
        "src/gateway/indexer.py",
        "src/gateway/models.py",
        "src/gateway/adapters/base.py",
        "src/gateway/adapters/claude.py",
        # Common names
        "src/main.py",
        "src/utils.py",
        "src/config.ts",
        "tests/test_main.py",
        "tests/test_utils.py",
        # Edge cases
        "README.md",
        "pyproject.toml",
        "setup.cfg",
        "Makefile",
    ]
    for f in files:
        p = tmp_path / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {f}\n")
    (tmp_path / ".gitignore").write_text("")
    return str(tmp_path)


@pytest.fixture
def indexed_tree(search_tree):
    """Pre-indexed FuzzyIndexer for search_tree."""
    idx = FuzzyIndexer(search_tree)
    idx._sync_build_index()
    return idx._files, idx._basenames


@pytest.fixture
def large_indexed(tmp_path):
    """10K+ entry index for performance benchmarks."""
    dirs = ["src", "lib", "tests", "docs", "scripts", "config"]
    extensions = [".py", ".ts", ".js", ".md", ".json", ".yaml"]
    for d in dirs:
        for sub in range(20):
            subdir = tmp_path / d / f"module_{sub:03d}"
            subdir.mkdir(parents=True, exist_ok=True)
            for i in range(80):
                ext = extensions[i % len(extensions)]
                f = subdir / f"file_{i:04d}{ext}"
                f.write_bytes(b"x")
    # Add some camelCase files for subsequence tests
    special = tmp_path / "src" / "components"
    special.mkdir(parents=True, exist_ok=True)
    for name in ["DataTransformer.py", "HttpClientPool.py", "EventDispatcher.ts", "TaskScheduler.js"]:
        (special / name).write_bytes(b"x")

    (tmp_path / ".gitignore").write_text("")

    idx = FuzzyIndexer(str(tmp_path))
    idx._sync_build_index()
    return idx._files, idx._basenames


# ---------------------------------------------------------------------------
# Correctness tests — all strategies must agree on basic expectations
# ---------------------------------------------------------------------------

class TestCorrectness:
    """Verify all subsequence strategies find expected results."""

    @pytest.mark.parametrize("strategy_name", list(SUBSEQUENCE_STRATEGIES))
    def test_exact_basename(self, indexed_tree, strategy_name):
        files, basenames = indexed_tree
        strategy = STRATEGIES[strategy_name]
        results = strategy("indexer.py", files, basenames, limit=5)
        assert any("indexer.py" in r.filepath for r in results)

    @pytest.mark.parametrize("strategy_name", list(SUBSEQUENCE_STRATEGIES))
    def test_subsequence_camelcase(self, indexed_tree, strategy_name):
        """'dtveng' should match DataValidatorEngine.py via subsequence."""
        files, basenames = indexed_tree
        strategy = STRATEGIES[strategy_name]
        results = strategy("dtveng", files, basenames, limit=5)
        assert len(results) > 0, f"{strategy_name} found no results for 'dtveng'"
        assert any("DataValidatorEngine" in r.filepath for r in results), (
            f"{strategy_name} did not rank DataValidatorEngine in top 5"
        )

    @pytest.mark.parametrize("strategy_name", list(SUBSEQUENCE_STRATEGIES))
    def test_path_spanning_query(self, indexed_tree, strategy_name):
        """'src/gw' should match src/gateway/* via full path."""
        files, basenames = indexed_tree
        strategy = STRATEGIES[strategy_name]
        results = strategy("src/gw", files, basenames, limit=5)
        assert len(results) > 0, f"{strategy_name} found no results for 'src/gw'"
        assert any("src/gateway" in r.filepath for r in results)

    @pytest.mark.parametrize("strategy_name", list(SUBSEQUENCE_STRATEGIES))
    def test_no_match(self, indexed_tree, strategy_name):
        files, basenames = indexed_tree
        strategy = STRATEGIES[strategy_name]
        results = strategy("zzzzzzz", files, basenames, limit=5)
        assert len(results) == 0

    @pytest.mark.parametrize("strategy_name", list(SUBSEQUENCE_STRATEGIES))
    def test_camelcase_initials(self, indexed_tree, strategy_name):
        """'HCP' should match HttpClientPool.py."""
        files, basenames = indexed_tree
        strategy = STRATEGIES[strategy_name]
        results = strategy("HCP", files, basenames, limit=5)
        assert any("HttpClientPool" in r.filepath for r in results), (
            f"{strategy_name} did not find HttpClientPool for 'HCP'"
        )

    @pytest.mark.parametrize("strategy_name", list(SUBSEQUENCE_STRATEGIES))
    def test_directory_matches(self, indexed_tree, strategy_name):
        """Directories (trailing /) should be searchable."""
        files, basenames = indexed_tree
        strategy = STRATEGIES[strategy_name]
        results = strategy("gateway", files, basenames, limit=10)
        assert any(r.filepath.endswith("/") for r in results), (
            f"{strategy_name} did not return directory entries"
        )

    @pytest.mark.parametrize("strategy_name", list(STRATEGIES))
    def test_empty_query(self, indexed_tree, strategy_name):
        files, basenames = indexed_tree
        strategy = STRATEGIES[strategy_name]
        results = strategy("", files, basenames, limit=5)
        assert len(results) == 0

    @pytest.mark.parametrize("strategy_name", list(STRATEGIES))
    def test_limit_respected(self, indexed_tree, strategy_name):
        files, basenames = indexed_tree
        strategy = STRATEGIES[strategy_name]
        results = strategy("s", files, basenames, limit=3)
        assert len(results) <= 3


# ---------------------------------------------------------------------------
# Ranking quality — more specific matches should rank higher
# ---------------------------------------------------------------------------

class TestRanking:
    """Test that strategies produce sensible ranking order."""

    @pytest.mark.parametrize("strategy_name", list(SUBSEQUENCE_STRATEGIES))
    def test_exact_name_ranks_first(self, indexed_tree, strategy_name):
        """Exact basename match should rank above partial matches."""
        files, basenames = indexed_tree
        strategy = STRATEGIES[strategy_name]
        results = strategy("main.py", files, basenames, limit=10)
        assert len(results) > 0
        # src/main.py should rank above tests/test_main.py
        assert results[0].filepath == "src/main.py"

    @pytest.mark.parametrize("strategy_name", list(SUBSEQUENCE_STRATEGIES))
    def test_basename_match_ranks_above_path(self, indexed_tree, strategy_name):
        """Basename match gets bonus over path-only match."""
        files, basenames = indexed_tree
        strategy = STRATEGIES[strategy_name]
        results = strategy("base", files, basenames, limit=5)
        assert len(results) > 0
        # base.py (basename hit) should rank above paths that happen to contain 'base'
        top_filepath = results[0].filepath
        assert "base.py" in top_filepath


# ---------------------------------------------------------------------------
# Performance benchmarks
# ---------------------------------------------------------------------------

class TestPerformance:
    """Benchmark all strategies on 10K+ file index."""

    PERF_QUERIES = ["module", "file_0042", "config", "htclp", "src/mod", "DataTrans"]

    @pytest.mark.parametrize("strategy_name", list(STRATEGIES))
    def test_latency_under_300ms(self, large_indexed, strategy_name):
        files, basenames = large_indexed
        strategy = STRATEGIES[strategy_name]

        for query in self.PERF_QUERIES:
            t0 = time.perf_counter()
            results = strategy(query, files, basenames, limit=20)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert elapsed_ms < 300, (
                f"{strategy_name} query '{query}' took {elapsed_ms:.0f}ms (limit 300ms)"
            )

    def test_comparative_benchmark(self, large_indexed, capsys):
        """Print comparative timings for all strategies (informational)."""
        files, basenames = large_indexed
        print(f"\n{'Strategy':<20} {'Query':<12} {'Time (ms)':>10} {'Results':>8}")
        print("-" * 54)

        for strategy_name, strategy in STRATEGIES.items():
            for query in self.PERF_QUERIES:
                t0 = time.perf_counter()
                results = strategy(query, files, basenames, limit=20)
                elapsed_ms = (time.perf_counter() - t0) * 1000
                print(f"{strategy_name:<20} {query:<12} {elapsed_ms:>10.1f} {len(results):>8}")
