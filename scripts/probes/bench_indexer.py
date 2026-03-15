#!/usr/bin/env python3
"""Benchmark: directory scanning and fuzzy search approaches.

Runs against the actual project CWD to measure real-world performance.
Compares:
  Scanning:  os.walk vs os.scandir (recursive) vs scandir-rs
  Matching:  substring vs rapidfuzz.fuzz.WRatio vs rapidfuzz.process.extract

Usage:
    python scripts/probes/bench_indexer.py [directory]
    python scripts/probes/bench_indexer.py              # defaults to project root
"""

import os
import sys
import time
from pathlib import Path
from typing import List, Tuple

import pathspec

# Hardcoded exclusions (from GatewayNodeConfig)
HARDCODED_IGNORE = {".git", "node_modules", ".next", "__pycache__", "venv", ".venv"}


# ---------------------------------------------------------------------------
# Scanning approaches
# ---------------------------------------------------------------------------

def scan_os_walk(root: str, spec: pathspec.PathSpec) -> List[str]:
    """Pure os.walk with pathspec filtering."""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune hardcoded dirs in-place
        dirnames[:] = [d for d in dirnames if d not in HARDCODED_IGNORE]
        # Prune pathspec-matched dirs
        dirnames[:] = [
            d for d in dirnames
            if not spec.match_file(os.path.relpath(os.path.join(dirpath, d), root) + "/")
        ]
        for f in filenames:
            rel = os.path.relpath(os.path.join(dirpath, f), root)
            if not spec.match_file(rel):
                files.append(rel)
    return files


def scan_os_scandir_recursive(root: str, spec: pathspec.PathSpec) -> List[str]:
    """Recursive os.scandir with pathspec filtering."""
    files = []

    def _walk(path: str):
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name in HARDCODED_IGNORE:
                            continue
                        rel = os.path.relpath(entry.path, root) + "/"
                        if spec.match_file(rel):
                            continue
                        _walk(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        rel = os.path.relpath(entry.path, root)
                        if not spec.match_file(rel):
                            files.append(rel)
        except PermissionError:
            pass

    _walk(root)
    return files


def scan_scandir_rs(root: str, spec: pathspec.PathSpec) -> List[str]:
    """scandir-rs (Rust) with post-filtering via pathspec."""
    from scandir_rs import Walk

    files = []
    walk = Walk(root, skip_hidden=False)
    for dirpath, dirnames, filenames in walk:
        full_dir = os.path.join(root, dirpath) if dirpath else root
        # Filter dirs — scandir-rs doesn't support in-place pruning,
        # so we filter files by checking path components
        for f in filenames:
            rel = os.path.join(dirpath, f) if dirpath else f
            parts = Path(rel).parts
            if any(p in HARDCODED_IGNORE for p in parts):
                continue
            if not spec.match_file(rel):
                files.append(rel)
    return files


# ---------------------------------------------------------------------------
# Fuzzy matching approaches
# ---------------------------------------------------------------------------

def match_substring(query: str, files: List[str], limit: int = 20) -> List[Tuple[str, float]]:
    """Simple case-insensitive substring match."""
    q = query.lower()
    results = []
    for f in files:
        name = os.path.basename(f).lower()
        if q in name:
            results.append((f, 1.0))
        elif q in f.lower():
            results.append((f, 0.5))
    return sorted(results, key=lambda x: -x[1])[:limit]


def match_rapidfuzz_wratio(query: str, files: List[str], limit: int = 20) -> List[Tuple[str, float]]:
    """rapidfuzz WRatio on basenames."""
    from rapidfuzz import fuzz
    results = []
    q = query.lower()
    for f in files:
        name = os.path.basename(f).lower()
        score = fuzz.WRatio(q, name)
        if score > 40:
            results.append((f, score))
    return sorted(results, key=lambda x: -x[1])[:limit]


def match_rapidfuzz_extract(query: str, files: List[str], limit: int = 20) -> List[Tuple[str, float]]:
    """rapidfuzz.process.extract — batch optimized."""
    from rapidfuzz import process, fuzz
    # Extract matches basenames in batch (C++ loop)
    basenames = [os.path.basename(f) for f in files]
    matches = process.extract(query, basenames, scorer=fuzz.WRatio, limit=limit, score_cutoff=40)
    return [(files[m[2]], m[1]) for m in matches]


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def load_gitignore(root: str) -> pathspec.PathSpec:
    """Load .gitignore + .nautexignore from root."""
    patterns = []
    for name in (".gitignore", ".nautexignore"):
        path = os.path.join(root, name)
        if os.path.exists(path):
            with open(path) as f:
                patterns.extend(f.read().splitlines())
    return pathspec.PathSpec.from_lines("gitignore", patterns)


def bench(name: str, func, *args, runs: int = 3):
    """Run func multiple times, report best/avg time and result size."""
    times = []
    result = None
    for _ in range(runs):
        t0 = time.perf_counter()
        result = func(*args)
        t1 = time.perf_counter()
        times.append(t1 - t0)
    best = min(times)
    avg = sum(times) / len(times)
    size = len(result) if result else 0
    print(f"  {name:35s}  best={best*1000:8.1f}ms  avg={avg*1000:8.1f}ms  results={size}")
    return result


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent.parent.parent.parent)
    print(f"Benchmark root: {root}\n")

    spec = load_gitignore(root)

    # --- Scanning ---
    print("=== Directory Scanning ===")
    files_walk = bench("os.walk + pathspec", scan_os_walk, root, spec, runs=3)
    files_scandir = bench("os.scandir recursive + pathspec", scan_os_scandir_recursive, root, spec, runs=3)

    try:
        files_rs = bench("scandir-rs + pathspec", scan_scandir_rs, root, spec, runs=3)
    except Exception as e:
        print(f"  scandir-rs: FAILED ({e})")
        files_rs = files_walk

    # Verify consistency
    set_walk = set(files_walk)
    set_scandir = set(files_scandir)
    set_rs = set(files_rs)
    print(f"\n  File counts: os.walk={len(set_walk)}  os.scandir={len(set_scandir)}  scandir-rs={len(set_rs)}")
    if set_walk != set_scandir:
        diff = set_walk.symmetric_difference(set_scandir)
        print(f"  WARNING: os.walk vs os.scandir differ by {len(diff)} files")
    if set_walk != set_rs:
        diff = set_walk.symmetric_difference(set_rs)
        print(f"  WARNING: os.walk vs scandir-rs differ by {len(diff)} files")

    files = files_walk  # use os.walk as baseline

    # --- Fuzzy Matching ---
    queries = ["gateway", "models", "harness", "intro", "config", "stream_consol"]
    print(f"\n=== Fuzzy Matching ({len(files)} files, {len(queries)} queries) ===")

    for query in queries:
        print(f"\n  Query: '{query}'")
        r_sub = bench(f"  substring", match_substring, query, files, runs=5)
        r_wr = bench(f"  rapidfuzz WRatio (loop)", match_rapidfuzz_wratio, query, files, runs=5)
        r_ext = bench(f"  rapidfuzz extract (batch)", match_rapidfuzz_extract, query, files, runs=5)

        # Show top 3 results from batch extract
        if r_ext:
            for path, score in r_ext[:3]:
                print(f"    → {score:5.1f}  {path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
