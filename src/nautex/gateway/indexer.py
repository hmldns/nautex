"""Async fuzzy file search indexer.

Maintains an in-memory index of the scoped local directory and serves
fuzzy search queries offloaded to a background thread via asyncio.to_thread.

Architecture:
- Scanning: os.scandir recursive with in-place directory pruning
- Filtering: pathspec (gitwildmatch) for .gitignore/.nautexignore + hardcoded defaults
- Matching: pluggable strategies — LCSseq hybrid (default), pure Python subsequence,
  regex-based, or pure LCSseq. All use subsequence matching (chars in order).

Performance (benchmarked on 38K files):
- Initial scan: ~290ms
- Per-query fuzzy match: ~15-30ms (LCSseq hybrid)
- File list cached in memory for repeat queries

Reference: MDSNAUTX-28, MDSNAUTX-31, MDSNAUTX-33
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import List, Optional, Protocol, Tuple

import pathspec
from pydantic import BaseModel
from rapidfuzz.distance import LCSseq
from rapidfuzz import process as rfprocess

logger = logging.getLogger(__name__)

# Hardcoded exclusions — always skipped regardless of ignore files.
# Matches GatewayNodeConfig.ignored_directories defaults.
HARDCODED_IGNORE = frozenset({
    ".git", "node_modules", ".next", "__pycache__", "venv", ".venv",
})

# Ignore file names to parse (in order of precedence)
IGNORE_FILES = (".gitignore", ".nautexignore")


class FileSnippet(BaseModel):
    """A matching snippet within a file."""
    line_number: int
    content: str
    match_score: float


class FileSearchResult(BaseModel):
    """A single file matching a fuzzy search query."""
    filepath: str
    snippets: List[FileSnippet] = []
    overall_score: float


class FuzzyIndexer:
    """In-memory fuzzy file search with pathspec filtering.

    Call build_index() once to scan the directory, then search() repeatedly.
    All heavy work runs in asyncio.to_thread to prevent event loop starvation.
    """

    def __init__(
        self,
        directory_scope: str,
        extra_ignore_patterns: Optional[List[str]] = None,
    ):
        self._scope = directory_scope
        self._extra_patterns = extra_ignore_patterns or []
        self._files: List[str] = []
        self._basenames: List[str] = []
        self._spec: Optional[pathspec.PathSpec] = None
        self._indexed = False

    @property
    def file_count(self) -> int:
        return len(self._files)

    @property
    def is_indexed(self) -> bool:
        return self._indexed

    async def build_index(self) -> int:
        """Scan directory and build in-memory file list. Returns file count."""
        count = await asyncio.to_thread(self._sync_build_index)
        return count

    async def search(self, query: str, limit: int = 20) -> List[FileSearchResult]:
        """Fuzzy search file paths. Offloaded to thread."""
        if not self._indexed:
            await self.build_index()
        return await asyncio.to_thread(self._sync_search, query, limit)

    # ------------------------------------------------------------------
    # Sync internals — run inside asyncio.to_thread
    # ------------------------------------------------------------------

    def _sync_build_index(self) -> int:
        """Scan directory tree, apply filters, cache file list."""
        self._spec = self._load_pathspec()
        self._files = self._scan_files()
        self._basenames = [os.path.basename(f.rstrip("/")) for f in self._files]
        self._indexed = True
        logger.info("Indexed %d entries in %s", len(self._files), self._scope)
        return len(self._files)

    def _sync_search(self, query: str, limit: int) -> List[FileSearchResult]:
        """Subsequence search against cached paths using the active strategy."""
        if not self._files or not query:
            return []
        return _strategy_lcsseq_hybrid(query, self._files, self._basenames, limit)

    def _load_pathspec(self) -> pathspec.PathSpec:
        """Load ignore patterns from .gitignore, .nautexignore, and extras."""
        patterns: List[str] = list(self._extra_patterns)
        for name in IGNORE_FILES:
            ignore_path = os.path.join(self._scope, name)
            if os.path.isfile(ignore_path):
                with open(ignore_path) as f:
                    patterns.extend(f.read().splitlines())
        return pathspec.PathSpec.from_lines("gitignore", patterns)

    def _scan_files(self) -> List[str]:
        """Recursive os.scandir with hardcoded + pathspec pruning.

        Returns both files and directories (dirs have trailing '/').
        Hidden entries (dot-prefixed) are always excluded.
        """
        files: List[str] = []
        spec = self._spec

        def _walk(path: str) -> None:
            try:
                with os.scandir(path) as it:
                    for entry in it:
                        if entry.name.startswith("."):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name in HARDCODED_IGNORE:
                                continue
                            rel = os.path.relpath(entry.path, self._scope) + "/"
                            if spec and spec.match_file(rel):
                                continue
                            files.append(rel)
                            _walk(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            rel = os.path.relpath(entry.path, self._scope)
                            if not spec or not spec.match_file(rel):
                                files.append(rel)
            except PermissionError:
                pass

        _walk(self._scope)
        return files


# ---------------------------------------------------------------------------
# Subsequence matching helpers
# ---------------------------------------------------------------------------

_BOUNDARY_CHARS = frozenset("/._-")


def _subsequence_positions(query_lower: str, candidate_lower: str) -> Optional[List[int]]:
    """Return match positions if query is a subsequence of candidate, else None."""
    positions: List[int] = []
    qi = 0
    qlen = len(query_lower)
    for ci, ch in enumerate(candidate_lower):
        if qi < qlen and ch == query_lower[qi]:
            positions.append(ci)
            qi += 1
    return positions if qi == qlen else None


def _score_positions(positions: List[int], candidate: str) -> float:
    """Score quality of a subsequence match based on boundary and consecutive bonuses."""
    score = 0.0
    for i, pos in enumerate(positions):
        # Consecutive bonus
        if i > 0 and positions[i - 1] == pos - 1:
            score += 3.0
        elif i > 0:
            gap = pos - positions[i - 1] - 1
            score -= min(gap * 0.5, 3.0)

        # Word boundary bonus
        if pos == 0:
            score += 2.0
        elif candidate[pos - 1] in _BOUNDARY_CHARS:
            score += 2.0
        elif candidate[pos].isupper() and candidate[pos - 1].islower():
            score += 2.0

    # Prefer earlier first match and shorter candidates
    if positions:
        score -= positions[0] * 0.1
    score -= len(candidate) * 0.01
    return score


def _score_entry(
    query_lower: str,
    filepath: str,
    basename: str,
) -> Optional[float]:
    """Score a file entry. Returns None if no subsequence match."""
    basename_lower = basename.lower()
    filepath_lower = filepath.lower()

    # Try basename first (more specific, gets bonus)
    positions = _subsequence_positions(query_lower, basename_lower)
    if positions is not None:
        return _score_positions(positions, basename) + 5.0

    # Fall back to full path
    positions = _subsequence_positions(query_lower, filepath_lower)
    if positions is not None:
        return _score_positions(positions, filepath)

    return None


# ---------------------------------------------------------------------------
# Search strategies
# ---------------------------------------------------------------------------

def _strategy_python_subsequence(
    query: str,
    files: List[str],
    basenames: List[str],
    limit: int,
) -> List[FileSearchResult]:
    """Strategy A: Pure Python subsequence filter + boundary scoring."""
    if not query or not files:
        return []
    query_lower = query.lower()
    scored: List[Tuple[int, float]] = []

    for i, filepath in enumerate(files):
        sc = _score_entry(query_lower, filepath, basenames[i])
        if sc is not None:
            scored.append((i, sc))

    scored.sort(key=lambda x: -x[1])
    max_sc = scored[0][1] if scored else 1.0
    norm = max(abs(max_sc), 1.0)
    return [
        FileSearchResult(
            filepath=files[idx],
            overall_score=max(0.0, min(1.0, sc / norm)),
        )
        for idx, sc in scored[:limit]
    ]


def _strategy_lcsseq_hybrid(
    query: str,
    files: List[str],
    basenames: List[str],
    limit: int,
) -> List[FileSearchResult]:
    """Strategy B: rapidfuzz LCSseq C++ filter + Python boundary scoring.

    Uses LCSseq.similarity as a batch filter (C++): a match means the query
    is a full subsequence of the candidate. Then applies Python scoring
    for ranking quality.
    """
    if not query or not files:
        return []
    query_lower = query.lower()
    qlen = len(query_lower)

    # C++ batch: find basenames where query is a subsequence
    basenames_lower = [b.lower() for b in basenames]
    basename_hits = rfprocess.extract(
        query_lower,
        basenames_lower,
        scorer=LCSseq.similarity,
        score_cutoff=qlen,
        limit=None,
    )
    hit_indices = {idx for _, _, idx in basename_hits}

    # Also check full paths for entries not matched by basename
    files_lower = [f.lower() for f in files]
    path_hits = rfprocess.extract(
        query_lower,
        files_lower,
        scorer=LCSseq.similarity,
        score_cutoff=qlen,
        limit=None,
    )
    for _, _, idx in path_hits:
        hit_indices.add(idx)

    # Score all hits with Python boundary scorer
    scored: List[Tuple[int, float]] = []
    for idx in hit_indices:
        sc = _score_entry(query_lower, files[idx], basenames[idx])
        if sc is not None:
            scored.append((idx, sc))

    scored.sort(key=lambda x: -x[1])
    max_sc = scored[0][1] if scored else 1.0
    norm = max(abs(max_sc), 1.0)
    return [
        FileSearchResult(
            filepath=files[idx],
            overall_score=max(0.0, min(1.0, sc / norm)),
        )
        for idx, sc in scored[:limit]
    ]


def _strategy_regex(
    query: str,
    files: List[str],
    basenames: List[str],
    limit: int,
) -> List[FileSearchResult]:
    """Strategy C: Regex-based subsequence filter + Python boundary scoring."""
    if not query or not files:
        return []
    query_lower = query.lower()
    # Build regex: each char separated by .*?
    pattern = ".*?".join(re.escape(ch) for ch in query_lower)
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error:
        return []

    scored: List[Tuple[int, float]] = []
    for i, filepath in enumerate(files):
        if rx.search(basenames[i]) or rx.search(filepath):
            sc = _score_entry(query_lower, filepath, basenames[i])
            if sc is not None:
                scored.append((i, sc))

    scored.sort(key=lambda x: -x[1])
    max_sc = scored[0][1] if scored else 1.0
    norm = max(abs(max_sc), 1.0)
    return [
        FileSearchResult(
            filepath=files[idx],
            overall_score=max(0.0, min(1.0, sc / norm)),
        )
        for idx, sc in scored[:limit]
    ]


def _strategy_lcsseq_pure(
    query: str,
    files: List[str],
    basenames: List[str],
    limit: int,
) -> List[FileSearchResult]:
    """Strategy D: Pure rapidfuzz LCSseq normalized_similarity (entirely C++).

    Fast but no boundary/consecutive awareness in ranking.
    """
    if not query or not files:
        return []
    query_lower = query.lower()
    basenames_lower = [b.lower() for b in basenames]

    matches = rfprocess.extract(
        query_lower,
        basenames_lower,
        scorer=LCSseq.normalized_similarity,
        limit=limit,
        score_cutoff=0.4,
    )

    return [
        FileSearchResult(
            filepath=files[idx],
            overall_score=score,
        )
        for _, score, idx in matches
    ]
