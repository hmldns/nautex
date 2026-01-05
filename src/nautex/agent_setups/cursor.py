"""Cursor agent setup and configuration."""
from pathlib import Path
from typing import Tuple, Optional

from .base import AgentRulesStatus
from .files_based_mcp import FilesBasedMCPAgentSetup
from ..models.config import AgentType
from ..prompts.common_workflow import get_common_workflow_prompt
from ..utils import path2display


class CursorAgentSetup(FilesBasedMCPAgentSetup):
    """Cursor agent setup and configuration.

    This class provides Cursor-specific implementation of the agent setup interface.
    """

    def __init__(self, config_service):
        """Initialize the Cursor agent setup."""
        super().__init__(config_service, AgentType.CURSOR)
        self.config_folder =  Path(".cursor")
        self.rules_filename = Path("nautex_workflow.mdc")
        self.rules_folder = self.config_folder / Path("rules")

    def get_agent_mcp_config_path(self) -> Path:
        """Get the full path to the MCP configuration file for the Cursor agent.

        Returns:
            Path object pointing to the .mcp.json file in the project root.
        """
        return self.config_folder / Path("mcp.json")

    def get_rules_path(self) -> Path:
        return self.cwd / self.rules_folder / self.rules_filename

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
        prompt = get_common_workflow_prompt(self.config_service.config.response_format)
        return f"""---
description: Workflow reference for Nautex MCP usage for project implementation guidance
globs: **/*
alwaysApply: true
---

{prompt}
"""

    def get_rules_info(self) -> str:
        return f"Rules Path: {path2display(self.get_rules_path())}"
