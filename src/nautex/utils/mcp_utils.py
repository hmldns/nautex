"""Utility functions for MCP configuration."""
import json
import logging
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Literal, Optional, Tuple

# Set up logging
logger = logging.getLogger(__name__)


class MCPConfigStatus(str, Enum):
    """Status of MCP configuration integration.

    Used to indicate the current state
    of the IDE's mcp.json configuration file.
    """
    OK = "OK"
    MISCONFIGURED = "MISCONFIGURED"
    NOT_FOUND = "NOT_FOUND"


# Default Nautex MCP configuration template
NAUTEX_CONFIG_TEMPLATE = {
    "nautex": {
        "command": "uvx",
        "args": ["nautex", "mcp"]
    }
}


def validate_mcp_file(mcp_path: Path) -> MCPConfigStatus:
    """Validate a specific mcp.json file for correct nautex configuration.

    Args:
        mcp_path: Path to the mcp.json file

    Returns:
        MCPConfigStatus indicating the validation result:
        - MCPConfigStatus.OK: Nautex entry exists and is correctly configured
        - MCPConfigStatus.MISCONFIGURED: File exists but nautex entry is incorrect
        - MCPConfigStatus.NOT_FOUND: No mcpServers section or nautex entry found
    """
    try:
        with open(mcp_path, 'r', encoding='utf-8') as f:
            mcp_config = json.load(f)

        # Check if mcpServers section exists
        if not isinstance(mcp_config, dict) or "mcpServers" not in mcp_config:
            logger.debug(f"No mcpServers section found in {mcp_path}")
            return MCPConfigStatus.NOT_FOUND

        mcp_servers = mcp_config["mcpServers"]
        if not isinstance(mcp_servers, dict):
            logger.debug(f"mcpServers is not a dict in {mcp_path}")
            return MCPConfigStatus.MISCONFIGURED

        # Check if nautex entry exists
        if "nautex" not in mcp_servers:
            logger.debug(f"No nautex entry found in mcpServers in {mcp_path}")
            return MCPConfigStatus.NOT_FOUND

        # Validate nautex entry against template
        nautex_config = mcp_servers["nautex"]
        if is_nautex_config_valid(nautex_config):
            logger.debug(f"Valid nautex configuration found in {mcp_path}")
            return MCPConfigStatus.OK
        else:
            logger.debug(f"Invalid nautex configuration found in {mcp_path}")
            return MCPConfigStatus.MISCONFIGURED

    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error reading/parsing mcp.json at {mcp_path}: {e}")
        return MCPConfigStatus.MISCONFIGURED


def is_nautex_config_valid(nautex_config: Any) -> bool:
    """Check if a nautex configuration entry matches our template.

    Args:
        nautex_config: The nautex configuration object from mcp.json

    Returns:
        True if configuration matches template, False otherwise
    """
    if not isinstance(nautex_config, dict):
        return False

    template_nautex_entry = NAUTEX_CONFIG_TEMPLATE.get("nautex")
    required_command = template_nautex_entry.get("command")
    required_args = template_nautex_entry.get("args")

    return (
        nautex_config.get("command") == required_command and
        nautex_config.get("args") == required_args
    )


def write_mcp_configuration(target_path: Path) -> bool:
    """Write or update MCP configuration with Nautex CLI server entry.

    Reads the target MCP configuration file (or creates if not exists), adds/updates
    the 'nautex' server entry in mcpServers object, and saves the file.

    Args:
        target_path: Path where the MCP configuration will be written

    Returns:
        True if configuration was successfully written, False otherwise
    """
    try:
        # Ensure parent directory exists
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing config or create new one
        mcp_config = {}

        if target_path.exists():
            try:
                with open(target_path, 'r', encoding='utf-8') as f:
                    mcp_config = json.load(f)
                logger.debug(f"Loaded existing mcp.json from {target_path}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Error reading existing mcp.json, creating new: {e}")
                mcp_config = {}
        else:
            logger.debug(f"Creating new mcp.json at {target_path}")

        # Ensure mcp_config is a dict
        if not isinstance(mcp_config, dict):
            logger.warning("Invalid mcp.json format, recreating")
            mcp_config = {}

        # Ensure mcpServers section exists
        if "mcpServers" not in mcp_config:
            mcp_config["mcpServers"] = {}
        elif not isinstance(mcp_config["mcpServers"], dict):
            logger.warning("mcpServers is not a dict, recreating")
            mcp_config["mcpServers"] = {}

        # Add/update nautex entry
        mcp_config["mcpServers"].update(NAUTEX_CONFIG_TEMPLATE.copy())

        # Write the configuration
        with open(target_path, 'w', encoding='utf-8') as f:
            json.dump(mcp_config, f, indent=2, ensure_ascii=False)

        logger.info(f"Successfully wrote Nautex MCP configuration to {target_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to write MCP configuration: {e}")
        return False