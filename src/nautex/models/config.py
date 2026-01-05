"""Pydantic models for configuration management."""
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, List
from pydantic import SecretStr, Field
from pydantic_settings import BaseSettings


class MCPOutputFormat(str, Enum):
    """Output format for MCP tool responses.

    Controls how MCP responses are serialized.
    """
    JSON = "json"
    MD_YAML = "md_yaml"  # Markdown with YAML code blocks


class AgentType(str, Enum):
    """Supported agent types.

    Used to identify the type of agent to use.
    """
    NOT_SELECTED = "not_selected"
    CURSOR = "cursor"
    CLAUDE = "claude"
    CODEX = "codex"
    OPENCODE = "opencode"
    GEMINI = "gemini"

    @classmethod
    def list(cls) -> List['AgentType']:
        """Get a list of all supported agent types.
        
        Returns:
            List of agent type values as strings.
        """
        return [agent_type for agent_type in cls]

    def display_name(self) -> str:

        if self == AgentType.NOT_SELECTED:
            return "Not Selected"
        elif self == AgentType.CURSOR:
            return "Cursor"
        elif self == AgentType.CLAUDE:
            return "Claude Code"
        elif self == AgentType.CODEX:
            return "Codex"
        elif self == AgentType.OPENCODE:
            return "OpenCode"
        elif self == AgentType.GEMINI:
            return "Gemini"
        return self.value.title()


class NautexConfig(BaseSettings):
    """Main configuration model using pydantic-settings for .env support.

    This model manages all configuration settings for the Nautex CLI,
    supporting both JSON file storage and environment variable overrides.
    """
    api_host: str = Field("https://api.nautex.ai", description="Base URL for the Nautex.ai API")
    api_token: Optional[SecretStr] = Field(None, description="Bearer token for Nautex.ai API authentication")

    agent_instance_name: str = Field("Coding Agent", description="User-defined name for this CLI instance")
    project_id: Optional[str] = Field(None, description="Selected Nautex.ai project ID")
    plan_id: Optional[str] = Field(None, description="Selected implementation plan ID")
    documents_path: Optional[str] = Field(None, description="Path to store downloaded documents")

    agent_type: Optional[AgentType] = Field(AgentType.NOT_SELECTED, description="AI agent to guide")
    response_format: MCPOutputFormat = Field(MCPOutputFormat.MD_YAML, description="MCP response format")

    class Config:
        """Pydantic configuration for environment variables and JSON files."""
        env_file = [] # we got custom loading calls
        env_file_encoding = "utf-8"
        env_prefix = "NAUTEX_"  # Environment variables should be prefixed with NAUTEX_k
        case_sensitive = False
        extra = "ignore"  # Ignore extra environment variables that don't match our model


    def get_token(self):
        """Get the API token from the config."""
        return self.api_token.get_secret_value() if self.api_token else None


    def to_config_dict(self) -> Dict:
        return self.model_dump(exclude_none=True,
                               exclude={"api_host", "api_token"} # don't serializing these 2
                              )
    @property
    def agent_type_selected(self) -> bool:
        return self.agent_type != AgentType.NOT_SELECTED
