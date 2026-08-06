"""Utility functions for MCP configuration in TOML format (Codex, Grok Build, etc.).

Strict TOML parsing via `tomli` (Python 3.10).
"""

from pathlib import Path
from typing import Any, Dict, Optional
import logging
import tomli

from .mcp_utils import MCPConfigStatus
import tomlkit

logger = logging.getLogger(__name__)


def _toml_load(path: Path) -> Dict[str, Any]:
    try:
        with open(path, "rb") as f:
            return tomli.load(f)
    except Exception as e:
        logger.error(f"Error reading/parsing TOML at {path}: {e}")
        raise


def _toml_dump(data: Dict[str, Any]) -> str:
    # Use tomlkit to serialize, it handles quoting and formatting correctly
    return tomlkit.dumps(data)


def validate_mcp_toml_file(mcp_path: Path, cwd: Path | None = None) -> MCPConfigStatus:
    try:
        if not mcp_path.exists():
            return MCPConfigStatus.NOT_FOUND

        config = _toml_load(mcp_path)

        if not isinstance(config, dict) or "mcp_servers" not in config:
            return MCPConfigStatus.NOT_FOUND

        servers = config.get("mcp_servers")
        if not isinstance(servers, dict):
            return MCPConfigStatus.MISCONFIGURED

        nautex = servers.get("nautex")
        if not isinstance(nautex, dict):
            return MCPConfigStatus.NOT_FOUND

        if nautex.get("command") != "uvx":
            return MCPConfigStatus.MISCONFIGURED
        if nautex.get("args") != ["nautex", "mcp"]:
            return MCPConfigStatus.MISCONFIGURED

        return MCPConfigStatus.OK
    except Exception as e:
        logger.error(f"Error validating TOML MCP file: {e}")
        return MCPConfigStatus.MISCONFIGURED


def write_mcp_toml_configuration(
    target_path: Path,
    cwd: Path | None = None,
    *,
    entry_extras: Optional[Dict[str, Any]] = None,
) -> bool:
    """Write or merge a Nautex MCP server entry into a TOML config.

    Args:
        target_path: Path to the agent TOML config (e.g. `.codex/config.toml`).
        cwd: Unused; kept for call-site compatibility.
        entry_extras: Optional extra fields merged into ``mcp_servers.nautex``
            (e.g. ``enabled``, ``startup_timeout_sec`` for Grok Build).
    """
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)

        base: Dict[str, Any] = {}
        if target_path.exists():
            base = _toml_load(target_path)
            if not isinstance(base, dict):
                base = {}

        # Ensure correct top-level table for Codex / Grok-style configs
        if "mcp_servers" not in base or not isinstance(base.get("mcp_servers"), dict):
            base["mcp_servers"] = {}

        nautex_entry: Dict[str, Any] = {
            "command": "uvx",
            "args": ["nautex", "mcp"],
        }
        if entry_extras:
            nautex_entry.update(entry_extras)

        base["mcp_servers"]["nautex"] = nautex_entry

        toml_text = _toml_dump(base)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(toml_text)
        logger.info(f"Successfully wrote Nautex MCP TOML configuration to {target_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to write TOML MCP configuration: {e}")
        return False
