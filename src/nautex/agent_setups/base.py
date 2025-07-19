"""Base class for agent setup and configuration."""
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple, List
import logging
import warnings

# Set up logging
logger = logging.getLogger(__name__)


class AgentRulesStatus(str, Enum):
    """Status of agent rules file.

    Used to indicate the current state of the agent rules file.
    """
    OK = "OK"
    OUTDATED = "OUTDATED"
    IOERROR = "IOERROR"
    NOT_FOUND = "NOT_FOUND"
    AGENT_TYPE_NOT_SELECTED = "AGENT_TYPE_NOT_SELECTED"



class AgentSetupBase(ABC):
    """Base class for agent setup and configuration.

    This class defines the interface for agent-specific setup and configuration.
    Concrete implementations should be provided for each supported agent type.
    """

    def __init__(self, config_service, agent_type: str):
        """Initialize the agent setup.

        Args:
            agent_type: The type of agent to setup
        """
        self.agent_type = agent_type
        self.config_service = config_service

    @property
    def cwd(self):
        return self.config_service.cwd

    @abstractmethod
    def get_agent_mcp_config_path(self) -> Optional[Path]:
        """Get the full path to the MCP configuration file for the agent type.

        Returns:
            Path object pointing to the MCP configuration file (e.g., .mcp.json in project root).

        Raises:
            ValueError: If the agent type is not supported.
        """
        return None


    @abstractmethod
    def get_rules_info(self) -> str:
        raise NotImplementedError


    def _validate_rules_file(self, rules_path: Path, expected_content: str) -> AgentRulesStatus:
        """Validate a specific rules file against the expected content.

        Args:
            rules_path: Path to the rules file
            cwd: The current working directory

        Returns:
            AgentRulesStatus indicating the validation result
        """
        try:
            # Read the existing rules file
            with open(rules_path, 'r', encoding='utf-8') as f:
                existing_content = f.read()

            # Compare the contents
            if existing_content == expected_content:
                logger.debug(f"Valid rules file found at {rules_path}")
                return AgentRulesStatus.OK
            else:
                logger.debug(f"Invalid rules file found at {rules_path}")
                return AgentRulesStatus.OUTDATED

        except IOError as e:
            logger.error(f"Error reading rules file at {rules_path}: {e}")
            return AgentRulesStatus.IOERROR


    @abstractmethod
    def validate_rules(self) -> Tuple[AgentRulesStatus, Optional[Path]]:
        raise UnboundLocalError()

    @abstractmethod
    def ensure_rules(self) -> bool:
        raise UnboundLocalError()


class AgentSetupNotSelected(AgentSetupBase):
    def get_agent_mcp_config_path(self) -> Optional[Path]:
        return None

    def get_rules_info(self):
        return "Agent Type not selected."

    def validate_rules(self) -> Tuple[AgentRulesStatus, Optional[Path]]:
        return AgentRulesStatus.AGENT_TYPE_NOT_SELECTED, Path("")

    def ensure_rules(self) -> bool:
        return False