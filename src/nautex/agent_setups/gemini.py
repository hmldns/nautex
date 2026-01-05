"""Gemini agent setup and configuration."""
from pathlib import Path
from typing import Tuple, Optional

from .base import AgentRulesStatus, AgentSetupBase
from .files_based_mcp import FilesBasedMCPAgentSetup
from .section_managed_rules_mixin import ConfigAwareSectionManagedRulesMixin
from ..models.config import AgentType
from ..prompts.consts import (
    NAUTEX_SECTION_START,
    NAUTEX_SECTION_END,
    rules_reference_content_for,
    default_agents_rules_template_for,
    DIR_NAUTEX,
)
from ..services.section_managed_file_service import SectionManagedFileService
from ..utils import path2display


class GeminiAgentSetup(ConfigAwareSectionManagedRulesMixin, FilesBasedMCPAgentSetup):
    """Gemini agent setup and configuration.

    This class provides Gemini-specific implementation of the agent setup interface.
    """

    def __init__(self, config_service):
        super().__init__(config_service, AgentType.GEMINI)
        self.config_folder =  Path(".gemini")
        self.rules_filename = Path("GEMINI.md")
        self.section_service = SectionManagedFileService(NAUTEX_SECTION_START, NAUTEX_SECTION_END)

    def get_agent_mcp_config_path(self) -> Path:
        """Get the full path to the MCP configuration file for the Gemini agent.

        Returns:
            Path object pointing to the settings.json file in the project root.
        """
        return self.config_folder / Path("settings.json")

    def get_rules_path(self) -> Path:
        return self.cwd / Path(DIR_NAUTEX) / self.rules_filename

    @property
    def root_gemini_path(self) -> Path:
        """Path to the root GEMINI.md file (with reference section)."""
        return self.cwd / self.rules_filename

    def get_root_rules_path(self) -> Path:
        return self.root_gemini_path

    def get_rules_info(self) -> str:
        return f"Rules Path: {path2display(self.get_rules_path())}"

    def get_reference_section_content(self) -> str:
        return rules_reference_content_for("GEMINI.md")

    def get_default_rules_template(self) -> str:
        # Avoid relying on instance type (may be str in some contexts)
        return default_agents_rules_template_for("GEMINI.md", AgentType.GEMINI.display_name())
