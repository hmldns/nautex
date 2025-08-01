"""MCP Configuration Service for managing IDE mcp.json integration."""
from pathlib import Path
from typing import Tuple, Optional
import logging
import warnings
import asyncio

from . import ConfigurationService
from ..utils.mcp_utils import MCPConfigStatus

# Re-export MCPConfigStatus for backward compatibility
__all__ = ['MCPConfigService', 'MCPConfigStatus']

# Set up logging
logger = logging.getLogger(__name__)


class MCPConfigService:
    """Service for managing IDE's mcp.json configuration file.

    This service acts as a hub that delegates to the agent_setup for the implementation.
    It handles checking existing MCP configurations, validating them,
    and writing the Nautex CLI's MCP server entry to integrate with IDE tools.
    """

    def __init__(self, config_service: ConfigurationService):
        """Initialize the MCP configuration service.

        Args:
            config_service: The configuration service to use
        """
        self.config_service = config_service

    @property
    def agent_setup(self):
        return self.config_service.agent_setup

    async def check_mcp_configuration(self) -> Tuple[MCPConfigStatus, Optional[Path]]:
        """Check the status of MCP configuration integration.

        Checks if the MCP configuration file exists and validates the 'nautex' entry against template.

        Returns:
            Tuple of (status, path_to_config_file)
            - MCPConfigStatus.OK: Nautex entry exists and is correctly configured
            - MCPConfigStatus.MISCONFIGURED: File exists but nautex entry is incorrect
            - MCPConfigStatus.NOT_FOUND: No MCP configuration file found or no nautex entry
        """
        return await self.agent_setup.check_mcp_configuration()

    async def write_mcp_configuration(self) -> bool:
        """Write or update MCP configuration with Nautex CLI server entry.

        Reads the target MCP configuration file (or creates if not exists), adds/updates
        the 'nautex' server entry in mcpServers object, and saves the file.

        Returns:
            True if configuration was successfully written, False otherwise
        """
        return await self.agent_setup.write_mcp_configuration()

    async def get_configuration_info(self) -> str:
        """Get information about the MCP configuration.
        
        Returns:
            String with information about the MCP configuration
        """
        return await self.agent_setup.get_mcp_configuration_info()
