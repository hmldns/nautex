"""Files-based MCP agent setup and configuration."""
from abc import abstractmethod
from pathlib import Path
from typing import Optional, Tuple
import asyncio

from .base import AgentSetupBase
from ..utils.mcp_utils import MCPConfigStatus, validate_mcp_file, write_mcp_configuration
import logging

# Set up logging
logger = logging.getLogger(__name__)


class FilesBasedMCPAgentSetup(AgentSetupBase):
    """Base class for file-based MCP agent setup and configuration.

    This class provides a file-based implementation of the MCP configuration methods.
    It is intended to be used by agent setups that store MCP configuration in files.
    """

    @abstractmethod
    def get_agent_mcp_config_path(self) -> Optional[Path]:
        """Get the full path to the MCP configuration file for the agent type.

        Returns:
            Path object pointing to the MCP configuration file (e.g., .mcp.json in project root).

        Raises:
            ValueError: If the agent type is not supported.
        """
        raise NotImplementedError()

    def get_config_path(self) -> Path:
        return self.config_service.cwd / self.get_agent_mcp_config_path()

    async def get_mcp_configuration_info(self) -> str:
        """Get information about the MCP configuration.
        
        Returns:
            String with information about the MCP configuration path
        """
        return f"MCP Configuration Path: {self.get_agent_mcp_config_path()}"
        
    async def check_mcp_configuration(self) -> Tuple[MCPConfigStatus, Optional[Path]]:
        """Check the status of MCP configuration integration.

        Checks if the MCP configuration file exists and validates the 'nautex' entry against template.

        Returns:
            Tuple of (status, path_to_config_file)
            - MCPConfigStatus.OK: Nautex entry exists and is correctly configured
            - MCPConfigStatus.MISCONFIGURED: File exists but nautex entry is incorrect
            - MCPConfigStatus.NOT_FOUND: No MCP configuration file found or no nautex entry
        """
        # Get the MCP configuration path
        mcp_path = self.get_agent_mcp_config_path()
        
        # Use asyncio.to_thread to run the file operations in a separate thread
        if mcp_path is not None:
            path_exists = await asyncio.to_thread(lambda: (self.cwd / mcp_path).exists())
            if path_exists:
                # Pass the current working directory for cwd validation
                status = await asyncio.to_thread(validate_mcp_file, self.cwd / mcp_path, self.cwd)
                return status, self.cwd / mcp_path

        # No MCP configuration file found
        logger.debug(f"No MCP configuration file found at {mcp_path}")
        return MCPConfigStatus.NOT_FOUND, None
        
    async def write_mcp_configuration(self) -> bool:
        """Write or update MCP configuration with Nautex CLI server entry.

        Reads the target MCP configuration file (or creates if not exists), adds/updates
        the 'nautex' server entry in mcpServers object, and saves the file.
        
        The current working directory (cwd) is added to the configuration.

        Returns:
            True if configuration was successfully written, False otherwise
        """
        # Get the MCP configuration path
        target_path = self.cwd / self.get_agent_mcp_config_path()
        # Pass the current working directory to be added to the configuration
        return await asyncio.to_thread(write_mcp_configuration, target_path, self.cwd)