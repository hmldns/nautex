"""Async fuzzy file search indexer.

Maintains an in-memory index of the scoped local directory and serves
fuzzy search queries offloaded to a background thread via asyncio.to_thread.

Architecture:
- Scanning: os.scandir recursive with in-place directory pruning
- Filtering: pathspec (gitwildmatch) for .gitignore/.nautexignore + hardcoded defaults
- Matching: rapidfuzz.process.extract (C++ batch) with fuzz.WRatio scorer

Performance (benchmarked on 38K files):
- Initial scan: ~290ms
- Per-query fuzzy match: ~26ms
- File list cached in memory for repeat queries

Reference: MDSNAUTX-28, MDSNAUTX-31, MDSNAUTX-33
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import List, Optional

import pathspec
from pydantic import BaseModel
from rapidfuzz import fuzz, process

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
        self._basenames = [os.path.basename(f) for f in self._files]
        self._indexed = True
        logger.info("Indexed %d files in %s", len(self._files), self._scope)
        return len(self._files)

    def _sync_search(self, query: str, limit: int) -> List[FileSearchResult]:
        """Fuzzy match query against cached basenames using rapidfuzz."""
        if not self._files:
            return []

        matches = process.extract(
            query,
            self._basenames,
            scorer=fuzz.WRatio,
            limit=limit,
            score_cutoff=40,
        )

        return [
            FileSearchResult(
                filepath=self._files[idx],
                overall_score=score / 100.0,
            )
            for _, score, idx in matches
        ]

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
        """Recursive os.scandir with hardcoded + pathspec pruning."""
        files: List[str] = []
        spec = self._spec

        def _walk(path: str) -> None:
            try:
                with os.scandir(path) as it:
                    for entry in it:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name in HARDCODED_IGNORE:
                                continue
                            rel = os.path.relpath(entry.path, self._scope) + "/"
                            if spec and spec.match_file(rel):
                                continue
                            _walk(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            rel = os.path.relpath(entry.path, self._scope)
                            if spec and not spec.match_file(rel):
                                files.append(rel)
            except PermissionError:
                pass

        _walk(self._scope)
        return files
