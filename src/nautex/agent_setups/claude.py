"""Claude agent setup and configuration."""
import subprocess
import re
import asyncio
from pathlib import Path
from typing import Tuple, Optional, List, Dict

from .base import AgentSetupBase, AgentRulesStatus
from ..models.config import AgentType
from ..prompts.common_workflow import COMMON_WORKFLOW_PROMPT
from ..utils import path2display
from ..utils.mcp_utils import MCPConfigStatus
import logging

# Set up logging
logger = logging.getLogger(__name__)


class ClaudeAgentSetup(AgentSetupBase):
    """Claude agent setup and configuration.

    This class provides Claude-specific implementation of the agent setup interface.
    It uses process-based MCP configuration via the 'claude mcp' command.
    """

    def __init__(self, config_service):
        """Initialize the Claude agent setup."""
        super().__init__(config_service, AgentType.CLAUDE)
        
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
            
            if match:
                status_symbol = match.group(1)
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
        return self.cwd / "CLAUDE.md"

    def validate_rules(self) -> Tuple[AgentRulesStatus, Optional[Path]]:
        # Check if rules file exists
        rules_path = self.get_rules_path()

        if rules_path.exists():
            status = self._validate_rules_file(rules_path, self.workflow_rules_content)
            return status, rules_path

        return AgentRulesStatus.NOT_FOUND, None

    def ensure_rules(self) -> bool:
        try:
            # Get the rules path and content
            rules_path = self.get_rules_path()
            content = self.workflow_rules_content

            # Ensure parent directory exists
            rules_path.parent.mkdir(parents=True, exist_ok=True)

            # Write the rules file
            with open(rules_path, 'w', encoding='utf-8') as f:
                f.write(content)

            return True

        except Exception as e:
            return False

    @property
    def workflow_rules_content(self) -> str:
        return COMMON_WORKFLOW_PROMPT

    def get_rules_info(self) -> str:
        return f"Rules Path: {path2display(self.get_rules_path())}"
