"""MCP Configuration Service for managing IDE mcp.json integration."""
import importlib.resources
import json
import os
from enum import Enum
from pathlib import Path
from typing import Tuple, Optional, Dict, Any, Literal
import logging

from . import ConfigurationService

# Set up logging
logger = logging.getLogger(__name__)



class MCPConfigStatus(str, Enum):
    """Status of MCP configuration integration.

    Used by MCPConfigService to indicate the current state
    of the IDE's mcp.json configuration file.
    """
    OK = "OK"
    MISCONFIGURED = "MISCONFIGURED"
    NOT_FOUND = "NOT_FOUND"


class MCPConfigService:
    """Service for managing IDE's mcp.json configuration file.

    This service handles checking existing MCP configurations, validating them,
    and writing the Nautex CLI's MCP server entry to integrate with IDE tools
    like Cursor.
    """

    def __init__(self, config_service: ConfigurationService):
        """Initialize the MCP configuration service.

        Args:
            config_service: The configuration service to use
        """
        self.config_service = config_service

        self.nautex_config_template = {
            "nautex": {
              "command": "uvx",
              "args": ["nautex", "mcp"]
            }
        }

    @property
    def mcp_config_path(self):
        """Get the full path to the MCP configuration file.

        Returns:
            Path object pointing to the MCP configuration file.
        """
        return self.config_service.agent_setup.get_agent_mcp_config_path()

    def check_mcp_configuration(self) -> Tuple[MCPConfigStatus, Optional[Path]]:
        """Check the status of MCP configuration integration.

        Checks if the MCP configuration file exists and validates the 'nautex' entry against template.

        Returns:
            Tuple of (status, path_to_config_file)
            - MCPConfigStatus.OK: Nautex entry exists and is correctly configured
            - MCPConfigStatus.MISCONFIGURED: File exists but nautex entry is incorrect
            - MCPConfigStatus.NOT_FOUND: No MCP configuration file found or no nautex entry
        """
        # Get the MCP configuration path
        mcp_path = self.get_config_path()
        if mcp_path is not None and mcp_path.exists():
            status = self._validate_mcp_file(mcp_path)
            return status, mcp_path

        # No MCP configuration file found
        logger.debug(f"No MCP configuration file found at {mcp_path}")
        return MCPConfigStatus.NOT_FOUND, None

    def _validate_mcp_file(self, mcp_path: Path) -> MCPConfigStatus:
        """Validate a specific mcp.json file for correct nautex configuration.

        Args:
            mcp_path: Path to the mcp.json file

        Returns:
            MCPConfigStatus indicating the validation result
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
            if self._is_nautex_config_valid(nautex_config):
                logger.debug(f"Valid nautex configuration found in {mcp_path}")
                return MCPConfigStatus.OK
            else:
                logger.debug(f"Invalid nautex configuration found in {mcp_path}")
                return MCPConfigStatus.MISCONFIGURED

        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error reading/parsing mcp.json at {mcp_path}: {e}")
            return MCPConfigStatus.MISCONFIGURED

    def _is_nautex_config_valid(self, nautex_config: Any) -> bool:
        """Check if a nautex configuration entry matches our template.

        Args:
            nautex_config: The nautex configuration object from mcp.json

        Returns:
            True if configuration matches template, False otherwise
        """
        if not isinstance(nautex_config, dict):
            return False

        template_nautex_entry = self.nautex_config_template.get("nautex")
        required_command = template_nautex_entry.get("command")
        required_args = template_nautex_entry.get("args")

        return (
            nautex_config.get("command") == required_command and
            nautex_config.get("args") == required_args
        )

    def write_mcp_configuration(self) -> bool:
        """Write or update MCP configuration with Nautex CLI server entry.

        Reads the target MCP configuration file (or creates if not exists), adds/updates
        the 'nautex' server entry in mcpServers object, and saves the file.

        Returns:
            True if configuration was successfully written, False otherwise
        """
        try:
            # Get the MCP configuration path
            target_path = self.get_config_path()

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
            mcp_config["mcpServers"].update(self.nautex_config_template.copy())

            # Write the configuration
            with open(target_path, 'w', encoding='utf-8') as f:
                json.dump(mcp_config, f, indent=2, ensure_ascii=False)

            logger.info(f"Successfully wrote Nautex MCP configuration to {target_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to write MCP configuration: {e}")
            return False

    def get_config_path(self) -> Path:
        """Get the path where the MCP configuration will be written.

        Returns:
            Path where the MCP configuration will be written
        """
        # Get the MCP configuration path from the agent setup
        mcp_path = self.mcp_config_path

        # If the path is relative, make it absolute by prepending the current working directory
        if mcp_path is not None and mcp_path.is_absolute():
            return self.config_service.cwd / mcp_path

        return mcp_path
