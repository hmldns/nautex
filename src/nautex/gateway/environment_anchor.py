"""Environment anchor — persistent identity for gateway environments.

Manages `.nautex/gateway_env.json` (environment ID + identity snapshot)
and `.nautex/gateway.lock` (PID lockfile to prevent duplicate gateways).

The anchor file ties a directory to a stable environment_id that survives
gateway restarts and reconnections. Identity drift (hostname/username change)
is detected at startup and must be resolved before the gateway can proceed.
"""

from __future__ import annotations

import json
import logging
import os
import signal
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

NAUTEX_DIR = ".nautex"
ANCHOR_FILE = "gateway_env.json"
LOCK_FILE = "gateway.lock"


@dataclass
class IdentitySnapshot:
    hostname: str
    directory_scope: str
    username: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "hostname": self.hostname,
            "directory_scope": self.directory_scope,
            "username": self.username,
        }

    @staticmethod
    def from_dict(d: Dict[str, str]) -> IdentitySnapshot:
        return IdentitySnapshot(
            hostname=d["hostname"],
            directory_scope=d["directory_scope"],
            username=d["username"],
        )


@dataclass
class IdentityDrift:
    """Describes which identity fields changed."""
    field: str
    old_value: str
    new_value: str


@dataclass
class AnchorState:
    environment_id: str
    identity: IdentitySnapshot
    history: List[Dict]

    def to_dict(self) -> dict:
        return {
            "environment_id": self.environment_id,
            "identity": self.identity.to_dict(),
            "history": self.history,
        }


def _nautex_dir(directory_scope: str) -> Path:
    return Path(directory_scope) / NAUTEX_DIR


def _anchor_path(directory_scope: str) -> Path:
    return _nautex_dir(directory_scope) / ANCHOR_FILE


def _lock_path(directory_scope: str) -> Path:
    return _nautex_dir(directory_scope) / LOCK_FILE


# ---------------------------------------------------------------------------
# Anchor file operations
# ---------------------------------------------------------------------------

def read_anchor(directory_scope: str) -> Optional[AnchorState]:
    """Read the anchor file. Returns None if it doesn't exist or is invalid."""
    path = _anchor_path(directory_scope)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return AnchorState(
            environment_id=data["environment_id"],
            identity=IdentitySnapshot.from_dict(data["identity"]),
            history=data.get("history", []),
        )
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Invalid anchor file %s: %s", path, e)
        return None


def write_anchor(directory_scope: str, state: AnchorState) -> None:
    """Write the anchor file. Creates .nautex/ if needed."""
    nautex = _nautex_dir(directory_scope)
    nautex.mkdir(exist_ok=True)
    path = _anchor_path(directory_scope)
    path.write_text(json.dumps(state.to_dict(), indent=2) + "\n")
    logger.info("Anchor written: %s env=%s", path, state.environment_id)

    # Ensure gateway_env.json is in .gitignore
    _ensure_gitignored(nautex, ANCHOR_FILE)
    _ensure_gitignored(nautex, LOCK_FILE)


def _ensure_gitignored(nautex_dir: Path, filename: str) -> None:
    """Add filename to .nautex/.gitignore if not already present."""
    gitignore = nautex_dir / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if filename in content.splitlines():
            return
        gitignore.write_text(content.rstrip("\n") + "\n" + filename + "\n")
    else:
        gitignore.write_text(filename + "\n")


# ---------------------------------------------------------------------------
# Identity reconciliation
# ---------------------------------------------------------------------------

def detect_drift(
    stored: IdentitySnapshot,
    current: IdentitySnapshot,
) -> List[IdentityDrift]:
    """Compare stored identity against current system values. Returns list of drifted fields."""
    drifts = []
    for field in ("hostname", "directory_scope", "username"):
        old_val = getattr(stored, field)
        new_val = getattr(current, field)
        if old_val != new_val:
            drifts.append(IdentityDrift(field=field, old_value=old_val, new_value=new_val))
    return drifts


def format_drift_message(drifts: List[IdentityDrift]) -> str:
    """Format drift details for display."""
    lines = ["Environment identity changed since last run:"]
    for d in drifts:
        lines.append(f"  {d.field}: {d.old_value} → {d.new_value}")
    return "\n".join(lines)


def update_anchor_identity(
    directory_scope: str,
    state: AnchorState,
    new_identity: IdentitySnapshot,
    drifts: List[IdentityDrift],
) -> AnchorState:
    """Update the anchor with new identity, appending drift to history."""
    now = datetime.now(timezone.utc).isoformat()
    for d in drifts:
        state.history.append({
            "timestamp": now,
            "action": "updated",
            "field": d.field,
            "old": d.old_value,
            "new": d.new_value,
        })
    state.identity = new_identity
    write_anchor(directory_scope, state)
    return state


def create_anchor(
    directory_scope: str,
    environment_id: str,
    identity: IdentitySnapshot,
) -> AnchorState:
    """Create a new anchor file after first registration."""
    now = datetime.now(timezone.utc).isoformat()
    state = AnchorState(
        environment_id=environment_id,
        identity=identity,
        history=[{
            "timestamp": now,
            "action": "created",
            "identity": identity.to_dict(),
        }],
    )
    write_anchor(directory_scope, state)
    return state


class EnvironmentDriftError(Exception):
    """Raised in headless mode when identity drift is detected."""

    def __init__(self, drifts: List[IdentityDrift]):
        self.drifts = drifts
        msg = format_drift_message(drifts)
        msg += "\nRun gateway in interactive mode to resolve: nautex gateway"
        super().__init__(msg)


def reconcile_at_startup(
    directory_scope: str,
    current_identity: IdentitySnapshot,
    headless: bool,
) -> Optional[str]:
    """Check anchor file and reconcile identity at gateway startup.

    Returns environment_id to send in registration, or None for first run.

    Raises EnvironmentDriftError in headless mode if drift detected.
    In interactive mode, prompts the user to update or create new.
    """
    anchor = read_anchor(directory_scope)
    if not anchor:
        logger.info("No anchor file — first run, will receive environment_id from backend")
        return None

    drifts = detect_drift(anchor.identity, current_identity)
    if not drifts:
        logger.info("Anchor matched: environment_id=%s", anchor.environment_id)
        return anchor.environment_id

    # Identity drift detected
    if headless:
        raise EnvironmentDriftError(drifts)

    # Interactive mode — prompt user
    print("\n" + format_drift_message(drifts))
    print("\n[U]pdate existing environment  |  [N]ew environment")
    while True:
        choice = input("> ").strip().lower()
        if choice in ("u", "update"):
            update_anchor_identity(directory_scope, anchor, current_identity, drifts)
            logger.info("Anchor updated: environment_id=%s", anchor.environment_id)
            return anchor.environment_id
        elif choice in ("n", "new"):
            # Remove anchor — backend will create new environment
            _anchor_path(directory_scope).unlink(missing_ok=True)
            logger.info("Anchor cleared — will create new environment")
            return None
        else:
            print("Please enter 'u' (update) or 'n' (new)")


# ---------------------------------------------------------------------------
# Lockfile — prevent duplicate gateways per directory
# ---------------------------------------------------------------------------

def _is_process_alive(pid: int) -> bool:
    """Check if a process with given PID is alive."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def acquire_lock(directory_scope: str) -> None:
    """Acquire the gateway lockfile. Raises if another gateway is running.

    Writes current PID to .nautex/gateway.lock. Checks for stale locks.
    """
    lock = _lock_path(directory_scope)
    nautex = _nautex_dir(directory_scope)
    nautex.mkdir(exist_ok=True)

    if lock.exists():
        try:
            stored_pid = int(lock.read_text().strip())
            if _is_process_alive(stored_pid) and stored_pid != os.getpid():
                raise RuntimeError(
                    f"Another gateway is already running in this directory (PID {stored_pid}).\n"
                    f"Lock file: {lock}"
                )
            # Stale lock — process is dead
            logger.info("Removing stale lock (PID %d)", stored_pid)
        except ValueError:
            logger.warning("Invalid lock file content, overwriting")

    lock.write_text(str(os.getpid()) + "\n")
    logger.info("Lock acquired: %s (PID %d)", lock, os.getpid())


def release_lock(directory_scope: str) -> None:
    """Release the gateway lockfile."""
    lock = _lock_path(directory_scope)
    if lock.exists():
        try:
            stored_pid = int(lock.read_text().strip())
            if stored_pid == os.getpid():
                lock.unlink()
                logger.info("Lock released: %s", lock)
        except (ValueError, OSError):
            pass
