"""MCP Configuration Service for managing IDE mcp.json integration."""

import json
import os
from enum import Enum
from pathlib import Path
from typing import Tuple, Optional, Dict, Any, Literal
import logging

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

    def __init__(self, project_root: Optional[Path] = None):
        """Initialize the MCP config service.

        Args:
            project_root: Root directory for the project. Defaults to current working directory.
        """
        self.project_root = project_root or Path.cwd()

        # Load the MCP config template
        template_path = Path(__file__).parent.parent / "consts" / "mcp_config_template.json"
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                self.nautex_config_template = json.load(f)["mcpServers"]["nautex"]
        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to load MCP config template: {e}")
            # Fallback template
            self.nautex_config_template = {
                "command": "nautex",
                "args": ["mcp"]
            }

    def check_mcp_configuration(self) -> Tuple[MCPConfigStatus, Optional[Path]]:
        """Check the status of MCP configuration integration.

        Locates mcp.json file with priority: local ./.cursor/mcp.json, 
        then global ~/.cursor/mcp.json. Validates 'nautex' entry against template.

        Returns:
            Tuple of (status, path_to_config_file)
            - MCPConfigStatus.OK: Nautex entry exists and is correctly configured
            - MCPConfigStatus.MISCONFIGURED: File exists but nautex entry is incorrect
            - MCPConfigStatus.NOT_FOUND: No mcp.json file found or no nautex entry
        """
        # Check local .cursor/mcp.json first
        local_mcp_path = self.project_root / ".cursor" / "mcp.json"
        if local_mcp_path.exists():
            status = self._validate_mcp_file(local_mcp_path)
            return status, local_mcp_path

        # Check global ~/.cursor/mcp.json
        global_mcp_path = Path.home() / ".cursor" / "mcp.json"
        if global_mcp_path.exists():
            status = self._validate_mcp_file(global_mcp_path)
            return status, global_mcp_path

        # No mcp.json found
        logger.debug("No mcp.json file found in local or global .cursor directories")
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

        # Check required fields
        required_command = self.nautex_config_template["command"]
        required_args = self.nautex_config_template["args"]

        return (
            nautex_config.get("command") == required_command and
            nautex_config.get("args") == required_args
        )

    def write_mcp_configuration(self, location: Literal['global', 'local']) -> bool:
        """Write or update MCP configuration with Nautex CLI server entry.

        Reads the target mcp.json (or creates if not exists), adds/updates
        the 'nautex' server entry in mcpServers object, and saves the file.

        Args:
            location: Where to write the configuration
                     'global' - ~/.cursor/mcp.json
                     'local' - ./.cursor/mcp.json (in project root)

        Returns:
            True if configuration was successfully written, False otherwise
        """
        try:
            # Determine target path
            if location == 'global':
                target_path = Path.home() / ".cursor" / "mcp.json"
            elif location == 'local':
                target_path = self.project_root / ".cursor" / "mcp.json"
            else:
                raise ValueError(f"Invalid location: {location}. Must be 'global' or 'local'")

            # Ensure parent directory exists
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Load existing config or create new one
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
                mcp_config = {}

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
            mcp_config["mcpServers"]["nautex"] = self.nautex_config_template.copy()

            # Write the configuration
            with open(target_path, 'w', encoding='utf-8') as f:
                json.dump(mcp_config, f, indent=2, ensure_ascii=False)

            logger.info(f"Successfully wrote Nautex MCP configuration to {target_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to write MCP configuration to {location}: {e}")
            return False

    def get_recommended_location(self) -> Literal['local', 'global']:
        """Get the recommended location for MCP configuration.

        Returns 'local' if this appears to be a project-specific setup,
        'global' for system-wide configuration.

        Returns:
            Recommended location for MCP configuration
        """
        # Check if there's already a local .cursor directory
        local_cursor_dir = self.project_root / ".cursor"
        if local_cursor_dir.exists():
            return 'local'

        # Check if this looks like a development project (has common dev files)
        dev_indicators = [
            "package.json", "pyproject.toml", "Cargo.toml", "go.mod", 
            ".git", "src", "lib", "Makefile", "requirements.txt"
        ]

        for indicator in dev_indicators:
            if (self.project_root / indicator).exists():
                return 'local'

        # Default to global
        return 'global'
