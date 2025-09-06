"""Utility functions for OpenCode JSON/JSONC configuration.

We operate on the per-project `opencode.json` (JSON) file when possible.
If the file cannot be parsed as JSON (eg. JSONC with comments), we fall back
to creating or updating a minimal JSON file and writing a backup alongside.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Tuple
import logging

from .mcp_utils import MCPConfigStatus

logger = logging.getLogger(__name__)


REQUIRED_NAUTEX_MCP = {
    "type": "local",
    "command": ["uvx", "nautex", "mcp"],
    "enabled": True,
}


def _load_json_or_none(path: Path) -> Dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Unable to parse JSON at {path}: {e}")
        return None


def validate_opencode_config_file(config_path: Path) -> MCPConfigStatus:
    """Validate opencode config for the required Nautex MCP server entry.

    Rules per https://opencode.ai/docs/mcp-servers/:
    - under key `mcp`, ensure key `nautex` is an object
    - it must have `type` == 'local'
    - and `command` == ["uvx", "nautex", "mcp"]
    - `enabled` may be true (recommended) but is optional for validation if present it should be truthy
    """
    if not config_path.exists():
        return MCPConfigStatus.NOT_FOUND

    data = _load_json_or_none(config_path)
    if data is None:
        return MCPConfigStatus.MISCONFIGURED

    mcp = data.get("mcp")
    if not isinstance(mcp, dict):
        return MCPConfigStatus.NOT_FOUND

    nautex = mcp.get("nautex")
    if not isinstance(nautex, dict):
        return MCPConfigStatus.NOT_FOUND

    if nautex.get("type") != REQUIRED_NAUTEX_MCP["type"]:
        return MCPConfigStatus.MISCONFIGURED
    if nautex.get("command") != REQUIRED_NAUTEX_MCP["command"]:
        return MCPConfigStatus.MISCONFIGURED

    return MCPConfigStatus.OK


def write_opencode_config(config_path: Path) -> bool:
    """Write or update opencode config with a Nautex MCP server entry.

    - Reads existing JSON if possible and preserves unrelated fields
    - Otherwise writes a minimal valid JSON with `$schema` and `mcp.nautex`
    - Creates a one-time `.bak` backup if overwriting a non-empty, unparsable file
    """
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)

        data: Dict[str, Any] | None = None
        if config_path.exists():
            data = _load_json_or_none(config_path)

        backup_needed = config_path.exists() and data is None
        if backup_needed:
            bak = config_path.with_suffix(config_path.suffix + ".bak")
            try:
                if not bak.exists():
                    bak.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception:
                # best-effort backup
                pass

        if data is None or not isinstance(data, dict):
            data = {"$schema": "https://opencode.ai/config.json"}

        # Ensure mcp dict exists
        mcp = data.get("mcp")
        if not isinstance(mcp, dict):
            mcp = {}
            data["mcp"] = mcp

        # Upsert nautex entry
        mcp["nautex"] = REQUIRED_NAUTEX_MCP.copy()

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Failed to write opencode config at {config_path}: {e}")
        return False

