"""Claude agent setup and configuration."""
import subprocess
import re
import asyncio
from pathlib import Path
from typing import Tuple, Optional, List, Dict

from .base import AgentSetupBase, AgentRulesStatus
from .section_managed_rules_mixin import ConfigAwareSectionManagedRulesMixin
from ..models.config import AgentType
from ..prompts.consts import (
    NAUTEX_SECTION_START,
    NAUTEX_SECTION_END,
    DEFAULT_RULES_TEMPLATE,
    rules_reference_content_for,
    DIR_NAUTEX,
)
from ..services.section_managed_file_service import SectionManagedFileService
from ..utils import path2display
from ..utils.mcp_utils import MCPConfigStatus
import logging

# Set up logging
logger = logging.getLogger(__name__)


class ClaudeAgentSetup(ConfigAwareSectionManagedRulesMixin, AgentSetupBase):
    """Claude agent setup and configuration.

    This class provides Claude-specific implementation of the agent setup interface.
    It uses process-based MCP configuration via the 'claude mcp' command.
    """

    def __init__(self, config_service):
        """Initialize the Claude agent setup."""
        super().__init__(config_service, AgentType.CLAUDE)
        self.section_service = SectionManagedFileService(NAUTEX_SECTION_START, NAUTEX_SECTION_END)
        
    def get_agent_mcp_config_path(self) -> Path:
        """Get the full path to the MCP configuration file for the Claude agent.

        Note: This method is kept for compatibility, but Claude uses process-based
        configuration rather than file-based configuration.

        Returns:
            Path object pointing to a non-existent file.
        """
        return Path(".claude/mcp.json")
        
    async def get_mcp_configuration_info(self) -> str:
        """Get information about the MCP configuration.
        
        Returns:
            String with information about the MCP configuration
        """
        return "Claude MCP Configuration: Process-based (via 'claude mcp' command)"
        
    async def check_mcp_configuration(self) -> Tuple[MCPConfigStatus, Optional[Path]]:
        """Check the status of MCP configuration integration.

        Runs 'claude mcp list' command to check if nautex is configured.

        Returns:
            Tuple of (status, None)
            - MCPConfigStatus.OK: Nautex entry exists and is correctly configured
            - MCPConfigStatus.MISCONFIGURED: Nautex entry exists but is not connected
            - MCPConfigStatus.NOT_FOUND: No nautex entry found
        """
        try:
            # Run 'claude mcp list' command asynchronously
            process = await asyncio.create_subprocess_exec(
                "claude", "mcp", "list",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                logger.error(f"Error running 'claude mcp list': {stderr}")
                return MCPConfigStatus.NOT_FOUND, None
                
            # Parse the output to check for nautex
            output = stdout.decode("utf-8")
            
            # Look for a line like "nautex: uvx nautex mcp - ✓ Connected"
            nautex_pattern = r"nautex:\s+uvx\s+nautex\s+mcp\s+-\s+([✓✗])\s+(Connected|Error)"
            match = re.search(nautex_pattern, output)

            # Also check for debug setup: "nautex: uv run python -m nautex.cli mcp - ✓ Connected"
            nautex_pattern_debug = r"nautex:\s+uv\s+run\s+python\s+-m\s+nautex\.cli\s+mcp\s+-\s+([✓✗])\s+(Connected|Error)"
            match_debug_setup = re.search(nautex_pattern_debug, output)

            # Use whichever pattern matched
            final_match = match or match_debug_setup

            if final_match:
                status_symbol = final_match.group(1)
                if status_symbol == "✓":
                    return MCPConfigStatus.OK, None
                else:
                    return MCPConfigStatus.MISCONFIGURED, None
            else:
                return MCPConfigStatus.NOT_FOUND, None
                
        except Exception as e:
            logger.error(f"Error checking Claude MCP configuration: {e}")
            return MCPConfigStatus.NOT_FOUND, None
            
    async def write_mcp_configuration(self) -> bool:
        """Write or update MCP configuration with Nautex CLI server entry.

        Runs 'claude mcp add nautex -s local -- uvx nautex mcp' command to configure nautex.

        Returns:
            True if configuration was successfully written, False otherwise
        """
        try:
            # Run 'claude mcp add nautex' command asynchronously
            process = await asyncio.create_subprocess_exec(
                "claude", "mcp", "add", "nautex", "-s", "local", "--", "uvx", "nautex", "mcp",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await process.communicate()

            stderr_str = stderr.decode("utf-8")

            if process.returncode != 0 and 'nautex already exists' not in stderr_str:
                logger.error(f"Error running 'claude mcp add nautex': {stderr}")
                return False
                
            # Verify the configuration was added successfully
            status, _ = await self.check_mcp_configuration()
            return status == MCPConfigStatus.OK
                
        except Exception as e:
            logger.error(f"Error writing Claude MCP configuration: {e}")
            return False

    def get_rules_path(self,) -> Path:
        return self.cwd / DIR_NAUTEX / "CLAUDE.md"
    
    @property
    def root_claude_path(self) -> Path:
        """Path to the root CLAUDE.md file."""
        return self.cwd / "CLAUDE.md"

    def get_root_rules_path(self) -> Path:
        return self.root_claude_path

    def get_rules_info(self) -> str:
        return f"Rules Path: {path2display(self.get_rules_path())}"

    def get_reference_section_content(self) -> str:
        return rules_reference_content_for("CLAUDE.md")

    def get_default_rules_template(self) -> str:
        return DEFAULT_RULES_TEMPLATE
