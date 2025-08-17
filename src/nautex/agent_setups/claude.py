"""Claude agent setup and configuration."""
import subprocess
import re
import asyncio
from pathlib import Path
from typing import Tuple, Optional, List, Dict

from .base import AgentSetupBase, AgentRulesStatus
from ..models.config import AgentType
from ..prompts.common_workflow import COMMON_WORKFLOW_PROMPT
from ..prompts.consts import (
    NAUTEX_SECTION_START,
    NAUTEX_SECTION_END,
    NAUTEX_RULES_REFERENCE_CONTENT,
    DEFAULT_RULES_TEMPLATE
)
from ..services.section_managed_file_service import SectionManagedFileService
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
        return self.cwd / ".nautex" / "CLAUDE.md"
    
    @property
    def root_claude_path(self) -> Path:
        """Path to the root CLAUDE.md file."""
        return self.cwd / "CLAUDE.md"

    def validate_rules(self) -> Tuple[AgentRulesStatus, Optional[Path]]:
        """Validate both .nautex/CLAUDE.md and root CLAUDE.md reference section."""
        rules_path = self.get_rules_path()
        
        # Check if .nautex/CLAUDE.md exists with correct content
        if not rules_path.exists():
            return AgentRulesStatus.NOT_FOUND, None
            
        status = self._validate_rules_file(rules_path, self.workflow_rules_content)
        if status != AgentRulesStatus.OK:
            return status, rules_path
            
        # Also check if root CLAUDE.md has the reference section with correct content
        if not self.root_claude_path.exists():
            return AgentRulesStatus.OUTDATED, rules_path
            
        # Check if section exists and has correct content
        current_content = self.root_claude_path.read_text(encoding='utf-8')
        section_bounds = self.section_service.find_section_boundaries(current_content)
        
        if not section_bounds:
            return AgentRulesStatus.OUTDATED, rules_path
        
        # Extract and compare section content
        start, end = section_bounds
        current_section = current_content[start:end]
        # Use same format as in update_section method
        expected_section = f"{NAUTEX_SECTION_START}\n\n{NAUTEX_RULES_REFERENCE_CONTENT.strip()}\n\n{NAUTEX_SECTION_END}"
        
        if current_section.strip() != expected_section.strip():
            return AgentRulesStatus.OUTDATED, rules_path
            
        return AgentRulesStatus.OK, rules_path

    def ensure_rules(self) -> bool:
        """Ensure both .nautex/CLAUDE.md and root CLAUDE.md reference exist and are up-to-date."""
        try:
            # First check if everything is already valid
            status, _ = self.validate_rules()
            if status == AgentRulesStatus.OK:
                return True  # Nothing to do
            
            # Create/update full rules file in .nautex/CLAUDE.md
            rules_path = self.get_rules_path()
            rules_path.parent.mkdir(parents=True, exist_ok=True)
            rules_path.write_text(self.workflow_rules_content, encoding='utf-8')
            
            # Ensure root CLAUDE.md has reference section (preserving user content)
            # This will check content and only update if different
            self.section_service.ensure_file_with_section(
                self.root_claude_path,
                NAUTEX_RULES_REFERENCE_CONTENT,
                DEFAULT_RULES_TEMPLATE
            )
            
            # Validate again to confirm everything is OK
            final_status, _ = self.validate_rules()
            return final_status == AgentRulesStatus.OK

        except Exception as e:
            logger.error(f"Error ensuring rules: {e}")
            return False

    @property
    def workflow_rules_content(self) -> str:
        return COMMON_WORKFLOW_PROMPT

    def get_rules_info(self) -> str:
        return f"Rules Path: {path2display(self.get_rules_path())}"
