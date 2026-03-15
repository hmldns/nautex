#!/usr/bin/env python3
"""Pathspec validation probe — verifies gitwildmatch pattern matching.

Tests pathspec library against a mock nested directory structure
to confirm correct handling of:
- Standard ignores (node_modules, .git, __pycache__)
- Wildcard patterns (*.pyc, *.log)
- Directory patterns (build/)
- Negated rules (!important.log)
- Nested .gitignore files
- Edge cases (dotfiles, deeply nested matches)

Run: python tests/gateway/probe_pathspec.py
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

import pathspec

# ANSI
GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def create_mock_tree(root: str):
    """Create a realistic nested directory structure."""
    files = [
        # Normal source files — should be included
        "src/main.py",
        "src/utils.py",
        "src/gateway/indexer.py",
        "src/gateway/models.py",
        "src/gateway/adapters/base.py",
        "README.md",
        "pyproject.toml",
        ".nautexignore",

        # Should be excluded by hardcoded defaults
        ".git/config",
        ".git/HEAD",
        ".git/objects/ab/1234",
        "node_modules/express/index.js",
        "node_modules/.package-lock.json",
        "__pycache__/main.cpython-310.pyc",
        "src/__pycache__/utils.cpython-310.pyc",
        ".venv/bin/python",
        ".venv/lib/site-packages/pip/main.py",
        "venv/bin/activate",
        ".next/static/chunks/main.js",

        # Should be excluded by wildcard patterns
        "src/debug.log",
        "logs/app.log",
        "build/output.js",
        "build/assets/style.css",
        "dist/bundle.js",
        "src/temp.pyc",

        # Negated rule test — should be INCLUDED despite *.log pattern
        "logs/important.log",

        # Dotfiles — should be included (not in ignore)
        ".env.example",
        "src/.eslintrc.json",

        # Deeply nested — should be included
        "src/gateway/adapters/gemini/setup.py",
        "src/gateway/adapters/gemini/INTEGRATION_EFFORT_LOG.md",
    ]

    for f in files:
        path = Path(root) / f
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {f}\n")


GITIGNORE_CONTENT = """\
# Build artifacts
build/
dist/
*.pyc

# Logs
*.log

# But keep important logs
!important.log

# IDE
.idea/
.vscode/
"""

NAUTEXIGNORE_CONTENT = """\
# Nautex-specific ignores
.cursor/
.codex/
"""

HARDCODED_IGNORE = {".git", "node_modules", ".next", "__pycache__", "venv", ".venv"}


def scan_with_pathspec(root: str, spec: pathspec.PathSpec) -> list[str]:
    """Scan directory using os.scandir recursive + pathspec (our chosen approach)."""
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
    return sorted(files)


def check(label: str, condition: bool, detail: str = ""):
    """Print pass/fail for a check."""
    status = f"{GREEN}PASS{RESET}" if condition else f"{RED}FAIL{RESET}"
    extra = f" {DIM}({detail}){RESET}" if detail else ""
    print(f"  [{status}] {label}{extra}")
    return condition


def main():
    tmpdir = tempfile.mkdtemp(prefix="pathspec-probe-")
    print(f"{BOLD}=== Pathspec Validation Probe ==={RESET}")
    print(f"  Mock tree: {tmpdir}\n")

    try:
        # Setup
        create_mock_tree(tmpdir)
        (Path(tmpdir) / ".gitignore").write_text(GITIGNORE_CONTENT)
        (Path(tmpdir) / ".nautexignore").write_text(NAUTEXIGNORE_CONTENT)

        # Load patterns
        patterns = GITIGNORE_CONTENT.splitlines() + NAUTEXIGNORE_CONTENT.splitlines()
        spec = pathspec.PathSpec.from_lines("gitignore", patterns)

        # Scan
        files = scan_with_pathspec(tmpdir, spec)
        file_set = set(files)

        print(f"  Scanned {len(files)} files\n")
        for f in files:
            print(f"    {DIM}{f}{RESET}")
        print()

        # --- Checks ---
        all_pass = True

        print(f"{BOLD}--- Inclusion checks (should be found) ---{RESET}")
        all_pass &= check("src/main.py included", "src/main.py" in file_set)
        all_pass &= check("src/gateway/indexer.py included", "src/gateway/indexer.py" in file_set)
        all_pass &= check("src/gateway/adapters/base.py included", "src/gateway/adapters/base.py" in file_set)
        all_pass &= check("README.md included", "README.md" in file_set)
        all_pass &= check("pyproject.toml included", "pyproject.toml" in file_set)
        all_pass &= check(".env.example included (dotfile)", ".env.example" in file_set)
        all_pass &= check("src/.eslintrc.json included", "src/.eslintrc.json" in file_set)
        all_pass &= check("deeply nested setup.py included",
                          "src/gateway/adapters/gemini/setup.py" in file_set)

        print(f"\n{BOLD}--- Negated rule check ---{RESET}")
        all_pass &= check("logs/important.log INCLUDED (negated !important.log)",
                          "logs/important.log" in file_set)

        print(f"\n{BOLD}--- Exclusion checks (should NOT be found) ---{RESET}")
        all_pass &= check(".git/config excluded (hardcoded)",
                          ".git/config" not in file_set)
        all_pass &= check("node_modules/** excluded (hardcoded)",
                          not any(f.startswith("node_modules/") for f in file_set))
        all_pass &= check("__pycache__/** excluded (hardcoded)",
                          not any("__pycache__" in f for f in file_set))
        all_pass &= check(".venv/** excluded (hardcoded)",
                          not any(f.startswith(".venv/") for f in file_set))
        all_pass &= check("venv/** excluded (hardcoded)",
                          not any(f.startswith("venv/") for f in file_set))
        all_pass &= check(".next/** excluded (hardcoded)",
                          not any(f.startswith(".next/") for f in file_set))
        all_pass &= check("build/ excluded (gitignore dir pattern)",
                          not any(f.startswith("build/") for f in file_set))
        all_pass &= check("dist/ excluded (gitignore dir pattern)",
                          not any(f.startswith("dist/") for f in file_set))
        all_pass &= check("*.pyc excluded (gitignore wildcard)",
                          not any(f.endswith(".pyc") for f in file_set))
        all_pass &= check("*.log excluded (except negated)",
                          "src/debug.log" not in file_set)
        all_pass &= check("logs/app.log excluded",
                          "logs/app.log" not in file_set)

        print(f"\n{BOLD}--- Summary ---{RESET}")
        if all_pass:
            print(f"  {GREEN}All checks passed.{RESET}")
        else:
            print(f"  {RED}Some checks failed.{RESET}")
            sys.exit(1)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        print(f"\n  {DIM}Cleaned up {tmpdir}{RESET}")


if __name__ == "__main__":
    main()
