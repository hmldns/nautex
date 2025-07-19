"""Agent Rules Service for managing agent workflow rules files."""
from pathlib import Path
from typing import Tuple, Optional
import logging

from . import ConfigurationService
from ..agent_setups.base import AgentRulesStatus

# Set up logging
logger = logging.getLogger(__name__)


class AgentRulesService:
    """Service for managing agent workflow rules files.

    This service acts as a hub that delegates to the agent_base for the implementation.
    It handles checking existing agent rules files, validating them,
    and writing the rules files to integrate with agent tools.
    """

    def __init__(self, config_service: ConfigurationService):
        """Initialize the agent rules service.

        Args:
            config_service: The configuration service to use
        """
        self.config_service = config_service

    @property
    def agent_setup(self):
        return self.config_service.agent_setup

    # Alias methods for backward compatibility
    def validate_rules(self) -> Tuple[AgentRulesStatus, Optional[Path]]:
        """Check the status of agent rules file.

        Validates file content against expected content.

        Returns:
            Tuple of (status, path_to_rules_file)
            - AgentRulesStatus.OK: Rules file exists and is correctly configured
            - AgentRulesStatus.OUTDATED: File exists but content is incorrect
            - AgentRulesStatus.ERROR: There was an error reading/parsing the rules file
            - AgentRulesStatus.NOT_FOUND: No rules file found
        """
        return self.agent_setup.validate_rules()

    def ensure_rules(self) -> bool:
        """Ensure that the rules file exists and is up to date.

        Returns:
            True if rules file was successfully written, False otherwise
        """
        return self.agent_setup.ensure_rules()

    def get_rules_info(self) -> str:
        """Get the rendered string content for the rules file.

        Returns:
            Rendered string content for the rules file
        """
        return self.agent_setup.get_rules_info()
