"""ACP-adapter install helpers.

Bootstraps the npm-managed ACP adapters (`claude-agent-acp`,
`codex-acp`). Detection of install state is via
`gateway.config.list_available_agents()`; the human-readable status
report lives in `gateway.status`.

Public surface:
- NPM_ADAPTER_PACKAGES — executable -> npm package source of truth.
- prompt_install_missing_npm(yes=…) — interactive install loop for
  missing npm-managed adapters.
- run_npm_install(package) — thin subprocess wrapper.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Dict

from .config import list_available_agents


NPM_ADAPTER_PACKAGES: Dict[str, str] = {
    "claude-agent-acp": "@agentclientprotocol/claude-agent-acp",
    "codex-acp": "@agentclientprotocol/codex-acp",
}


def run_npm_install(package: str) -> subprocess.CompletedProcess:
    """Run `npm install -g <package>@latest`, streaming output.

    Raises FileNotFoundError if `npm` is not on PATH.
    """
    if not shutil.which("npm"):
        raise FileNotFoundError(
            "npm not found on PATH. Install Node.js (https://nodejs.org/) and retry."
        )
    spec = f"{package}@latest"
    print(f"Running: npm install -g {spec}")
    return subprocess.run(["npm", "install", "-g", spec], check=False)


def _confirm(prompt: str) -> bool:
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def prompt_install_missing_npm(*, yes: bool = False) -> None:
    """For each missing npm-managed adapter, prompt and install.

    Reassures the user about adapters already present; reports
    missing native binaries without attempting to install them.
    """
    agents = list_available_agents()
    npm_missing = []
    npm_present = []
    native_missing = []

    for agent_id, info in agents.items():
        reg = info["registration"]
        is_npm = reg.executable in NPM_ADAPTER_PACKAGES
        if is_npm:
            if info["installed"]:
                npm_present.append((agent_id, reg.executable, info["binary_path"]))
            else:
                npm_missing.append((agent_id, reg.executable))
        else:
            if not info["installed"] and reg.executable != "<built-in>":
                native_missing.append((agent_id, reg.executable))

    for agent_id, executable, path in npm_present:
        print(f"✓ {executable} already installed at {path}")

    for agent_id, executable in native_missing:
        print(f"{agent_id}: not installed — vendor binary, install separately")

    if not npm_missing:
        if npm_present:
            print("All npm-managed ACP adapters are installed.")
        return

    print()
    for agent_id, executable in npm_missing:
        package = NPM_ADAPTER_PACKAGES[executable]
        if yes:
            print(f"Installing {package} (--yes)")
            do_install = True
        else:
            do_install = _confirm(f"Install {package} via npm?")
        if not do_install:
            print(f"Skipped {package}.")
            continue
        try:
            result = run_npm_install(package)
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return
        if result.returncode != 0:
            print(f"npm install failed for {package} (exit {result.returncode})", file=sys.stderr)
            continue
        new_path = shutil.which(executable)
        if new_path:
            print(f"✓ {executable} installed at {new_path}")
        else:
            print(f"Warning: {executable} not found on PATH after install.", file=sys.stderr)
