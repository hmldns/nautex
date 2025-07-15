"""Agent Rules Service for managing agent workflow rules files."""
import importlib.resources
import os
from enum import Enum
from pathlib import Path
from typing import Tuple, Optional, Literal
import logging

from src.nautex.services import ConfigurationService
from src.nautex.models.config import NautexConfig

# Set up logging
logger = logging.getLogger(__name__)


class AgentRulesStatus(str, Enum):
    """Status of agent rules file.

    Used by AgentRulesService to indicate the current state
    of the agent rules file.
    """
    OK = "OK"
    OUTDATED = "OUTDATED"
    NOT_FOUND = "NOT_FOUND"


class AgentRulesService:
    """Service for managing agent workflow rules files.

    This service handles checking existing agent rules files, validating them,
    and writing the rules files to integrate with agent tools like Cursor.
    """

    def __init__(self, config_service: ConfigurationService):
        """Initialize the agent rules service.

        Args:
            config_service: The configuration service to use
            config: The Nautex configuration object
        """
        self.config_service = config_service

        # Get the package path for the rules file
        self.rules_file_name = "nautex_workflow.mdc"
        self.rules_package_path = "src.nautex.rules.cursor"
        self.rules_package_file = self.rules_file_name

    @property
    def rules_subpath(self):
        return self.config_service.config.get_agent_rules_folder()

    def check_rules_file(self) -> Tuple[AgentRulesStatus, Optional[Path]]:
        """Check the status of agent rules file.

        Locates rules file with priority: local ./{subpath}/{rules_file_name}, 
        then global ~/{subpath}/{rules_file_name}. Validates file content against package template.

        Returns:
            Tuple of (status, path_to_rules_file)
            - AgentRulesStatus.OK: Rules file exists and is correctly configured
            - AgentRulesStatus.INVALID: File exists but content is incorrect
            - AgentRulesStatus.NOT_FOUND: No rules file found
        """
        # Check local {subpath}/{rules_file_name} first
        local_rules_path = self.get_rules_path('local')
        if local_rules_path.exists():
            status = self._validate_rules_file(local_rules_path)
            return status, local_rules_path

        # Check global ~/{subpath}/{rules_file_name}
        global_rules_path = self.get_rules_path('global')
        if global_rules_path.exists():
            status = self._validate_rules_file(global_rules_path)
            return status, global_rules_path

        # No rules file found
        logger.debug(f"No {self.rules_file_name} file found in local or global {self.rules_subpath} directories")
        return AgentRulesStatus.NOT_FOUND, None

    def _validate_rules_file(self, rules_path: Path) -> AgentRulesStatus:
        """Validate a specific rules file against the package template.

        Args:
            rules_path: Path to the rules file

        Returns:
            AgentRulesStatus indicating the validation result
        """
        try:
            # Read the existing rules file
            with open(rules_path, 'r', encoding='utf-8') as f:
                existing_content = f.read()

            # Get the package template content
            package_content = self._get_package_rules_content()

            # Compare the contents
            if existing_content == package_content:
                logger.debug(f"Valid rules file found at {rules_path}")
                return AgentRulesStatus.OK
            else:
                logger.debug(f"Invalid rules file found at {rules_path}")
                return AgentRulesStatus.OUTDATED

        except IOError as e:
            logger.error(f"Error reading rules file at {rules_path}: {e}")
            return AgentRulesStatus.OUTDATED

    def _get_package_rules_content(self) -> str:
        """Get the content of the rules file from the package.

        Returns:
            Content of the rules file from the package
        """
        try:
            # Use importlib.resources to get the content of the file from the package
            package_path = importlib.resources.files(self.rules_package_path)
            file_path = package_path / self.rules_package_file

            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading package rules file: {e}")
            raise

    def write_rules_file(self, location: Literal['global', 'local'] = 'local') -> bool:
        """Write or update agent rules file.

        Writes the rules file from the package to the specified location.

        Args:
            location: Where to write the rules file
                     'global' - ~/{subpath}/{rules_file_name}
                     'local' - ./{subpath}/{rules_file_name} (in current working directory)

        Returns:
            True if rules file was successfully written, False otherwise
        """
        try:
            # Determine target path
            target_path = self.get_rules_path(location)

            # Ensure parent directory exists
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Get the package template content
            package_content = self._get_package_rules_content()

            # Write the rules file
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(package_content)

            logger.info(f"Successfully wrote agent rules file to {target_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to write agent rules file to {location}: {e}")
            return False

    def get_recommended_location(self) -> Literal['local', 'global']:
        """Get the recommended location for agent rules file.

        Returns 'local' if this appears to be a project-specific setup,
        'global' for system-wide configuration.

        Returns:
            Recommended location for agent rules file
        """
        # For now preferring always local
        return 'local'

    def get_rules_path(self, location: Optional[Literal['global', 'local']] = None) -> Path:
        """Get the path where the agent rules file will be written.

        Args:
            location: The location to get the path for.
                     If None, uses the recommended location.

        Returns:
            Path where the agent rules file will be written
        """
        if location is None:
            location = self.get_recommended_location()

        if location == 'global':
            return Path.home() / self.rules_subpath / self.rules_file_name
        else:  # local
            return self.config_service.cwd / self.rules_subpath / self.rules_file_name
