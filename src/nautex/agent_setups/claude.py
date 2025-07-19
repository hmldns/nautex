"""Claude agent setup and configuration."""
from pathlib import Path
from typing import Tuple, Optional

from .base import AgentSetupBase, AgentRulesStatus
from ..models.config import AgentType
from ..prompts.common_workflow import COMMON_WORKFLOW_PROMPT
from ..utils import path2display


class ClaudeAgentSetup(AgentSetupBase):
    """Claude agent setup and configuration.

    This class provides Claude-specific implementation of the agent setup interface.
    It supports .mcp.json for JSON config and CLAUDE.md in project root folder.
    """

    def __init__(self, config_service):
        """Initialize the Claude agent setup."""
        super().__init__(config_service, AgentType.CLAUDE)

    def get_agent_mcp_config_path(self) -> Path:
        """Get the full path to the MCP configuration file for the Claude agent.

        Returns:
            Path object pointing to the .mcp.json file in the project root.
        """
        return Path(".mcp.json")

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
