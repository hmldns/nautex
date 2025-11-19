"""Configuration service for loading and saving Nautex CLI settings."""
import gc
import json
import os
import stat
import platform
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from pydantic import ValidationError

from ..models.config import NautexConfig, AgentType
from ..agent_setups.base import AgentSetupBase, AgentSetupNotSelected
from ..agent_setups.cursor import CursorAgentSetup
from ..agent_setups.claude import ClaudeAgentSetup
from ..agent_setups.codex import CodexAgentSetup
from ..agent_setups.opencode import OpenCodeAgentSetup
from ..agent_setups.gemini import GeminiAgentSetup
from ..prompts.consts import DIR_NAUTEX, DIR_NAUTEX_DOCS


class ConfigurationError(Exception):
    """Custom exception for configuration-related errors."""
    pass


class ConfigurationService:
    """Service for managing Nautex CLI configuration settings.

    This service handles loading configuration from .nautex/config.json and
    optionally from environment variables via .env file support. It also
    manages saving configuration with appropriate file permissions.
    """

    def __init__(self, project_root: Optional[Path] = None):
        """Initialize the configuration service.

        Args:
            project_root: Root directory for the project. Defaults to current working directory.
        """

        self.project_root = project_root or Path.cwd()
        self.config_dir = self.project_root / self.nautex_dir
        self.config_file = self.config_dir / "config.json"
        self.env_file = self.project_root / ".env"
        self.nautex_env_file = self.project_root / self.nautex_dir / ".env"

        self._config: Optional[NautexConfig] = None

    @property
    def config(self) -> NautexConfig:
        return self._config

    @property
    def cwd(self) -> Path :
        return Path.cwd()

    @property
    def nautex_dir(self):
        return Path(DIR_NAUTEX)

    @property
    def documents_path(self) -> Path :
        if self.config.documents_path:
            return Path(self.config.documents_path)
        else:
            return Path(DIR_NAUTEX_DOCS)

    @property
    def agent_setup(self) -> Optional[AgentSetupBase]:
        """Get the agent setup base for the configured agent type.

        Returns:
            AgentSetupBase implementation for the configured agent type.

        Raises:
            ValueError: If the agent type is not supported.
        """
        if self.config.agent_type == AgentType.CURSOR:
            return CursorAgentSetup(self)
        elif self.config.agent_type == AgentType.CLAUDE:
            return ClaudeAgentSetup(self)
        elif self.config.agent_type == AgentType.CODEX:
            return CodexAgentSetup(self)
        elif self.config.agent_type == AgentType.OPENCODE:
            return OpenCodeAgentSetup(self)
        elif self.config.agent_type == AgentType.GEMINI:
            return GeminiAgentSetup(self)
        else:
            return AgentSetupNotSelected(self, AgentType.NOT_SELECTED.value)

    def get_supported_agent_types(self) -> List[AgentType]:
        """Get a list of supported agent types.

        Returns:
            List of supported agent types as strings.
        """
        return AgentType.list()

    def load_configuration(self) -> NautexConfig:
        """Load configuration from .nautex/config.json and environment variables.

        The configuration is loaded with the following precedence:
        1. Environment variables (with NAUTEX_ prefix)
        2. .env file in project root
        3. .env file in .nautex/ folder
        4. .nautex/config.json file
        5. Default values from the model

        Returns:
            NautexConfig: Loaded and validated configuration

        Raises:
            ConfigurationError: If configuration cannot be loaded or is invalid
        """
        try:
            # Load environment variables first (they have highest precedence)
            env_vars = self._load_environment_variables()

            # Load from config file if it exists
            config_data = {}
            if self.config_file.exists():
                try:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                except json.JSONDecodeError as e:
                    raise ConfigurationError(f"Invalid JSON in config file: {e}")
                except IOError as e:
                    raise ConfigurationError(f"Cannot read config file: {e}")

            # Merge config file data with environment variables (env vars take precedence)
            merged_config = {**config_data, **env_vars}

            # Create NautexConfig with merged data
            # pydantic-settings will also automatically check for env vars with NAUTEX_ prefix
            NautexConfig.Config.case_sensitive = [".env", self.nautex_env_file]
            NautexConfig.model_rebuild()
            try:
                config = NautexConfig(**merged_config)
            except ValidationError as e:
                raise ConfigurationError(f"Invalid configuration data: {e}")

            self._config = config

            return config

        except Exception as e:
            if isinstance(e, ConfigurationError):
                raise
            raise ConfigurationError(f"Unexpected error loading configuration: {e}")


    def _load_nautex_vars(self, filename: str):
        """
        Loads a .env-like text file in binary mode line by line to minimize time other's sensitive data is held in memory.

        :param filename: Path to the file to load.
        :return: Dict of relevant NAUTEX_ variables (keys: str, values: bytearray).
        """
        result = {}
        # Convert prefix to bytes using utf-8 encoding
        prefix_bytes = NautexConfig.Config.env_prefix.encode('utf-8')
        with open(filename, 'rb', buffering=120) as f:
            for line_bytes in f:
                # Convert to bytearray for mutability and shredding
                line = bytearray(line_bytes.strip())

                if prefix_bytes in line and b'=' in line:
                    try:
                        # Split on first '=' (keep as bytes)
                        key_bytes, value_bytes = line.split(b'=', 1)
                        key_str = key_bytes.decode('utf-8').strip()
                        value = value_bytes.decode('utf-8').strip()
                        result[key_str] = value
                    except ValueError:
                        pass  # Skip malformed lines
                else:
                    # Shred non-matching line: overwrite with zeros
                    for i in range(len(line)):
                        line[i] = 0

                # Delete reference to encourage deallocation (shredded data is already cleared)
                del line

        gc.collect()  # Force GC to reclaim sooner 

        return result

    def _load_environment_variables(self) -> Dict[str, Any]:
        """Load environment variables with NAUTEX_ prefix.

        Reads env files directly and filters out non-relevant lines in memory.

        Returns:
            Dict with environment variable values (keys without NAUTEX_ prefix)
        """
        env_vars = {}
        prefix = NautexConfig.Config.env_prefix

        # Check for environment variables with NAUTEX_ prefix
        env_vars = {k: v for k, v in os.environ.items() if k.startswith(prefix)}

        if self.env_file.exists():
            cfg = self._load_nautex_vars(str(self.env_file))
            env_vars.update(cfg)

        if self.nautex_env_file.exists():
            cfg = self._load_nautex_vars(str(self.nautex_env_file))
            env_vars.update(cfg)

        # Remove prefix and convert to lowercase
        env_vars = {k[len(prefix):].lower(): v for k, v in env_vars.items()}

        return env_vars

    def save_configuration(self, config_data: Optional[NautexConfig] = None) -> None:
        if config_data is None:
            config_data = self._config

        try:
            # Ensure .nautex directory exists
            self.config_dir.mkdir(exist_ok=True)

            # Write JSON to file
            config_dict = config_data.to_config_dict()
            try:
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(config_dict, f, indent=2, ensure_ascii=False)
            except IOError as e:
                raise ConfigurationError(f"Cannot write config file: {e}")

        except Exception as e:
            if isinstance(e, ConfigurationError):
                raise
            raise ConfigurationError(f"Unexpected error saving configuration: {e}")

    # need that to avoid messing with user's env and making json config git commitable
    def save_token_to_nautex_env(self, token: str):
        self.nautex_env_file.parent.mkdir(exist_ok=True)
        
        # Read existing content
        existing_lines = []
        token_key = NautexConfig.Config.env_prefix + 'api_token'.upper()
        token_found = False
        
        if self.nautex_env_file.exists():
            with open(self.nautex_env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(f"{token_key}="):
                        # Replace existing token
                        existing_lines.append(f"{token_key}={token}")
                        token_found = True
                    elif line:  # Keep non-empty lines that aren't the token
                        existing_lines.append(line)
        
        # Add token if it wasn't found
        if not token_found:
            existing_lines.append(f"{token_key}={token}")
        
        # Write back all lines
        with open(self.nautex_env_file, 'w') as f:
            for line in existing_lines:
                f.write(f"{line}\n")

        self._ensure_gitignore(self.nautex_env_file.parent)

    def _ensure_gitignore(self, path: Path):
        """Ensure .gitignore exists in .nautex dir with .env entry."""
        gitignore_path = path / ".gitignore"
        if not gitignore_path.exists():
            with open(gitignore_path, 'w') as f:
                f.write(".env\n")

    def config_exists(self) -> bool:
        """Check if a configuration file exists.

        Returns:
            True if .nautex/config.json exists, False otherwise
        """
        return self.config_file.exists()

    def get_config_path(self) -> Path:
        """Get the path to the configuration file.

        Returns:
            Path to the configuration file
        """
        return self.config_file

    def delete_configuration(self) -> None:
        """Delete the configuration file if it exists.

        Raises:
            ConfigurationError: If file cannot be deleted
        """
        if self.config_file.exists():
            try:
                self.config_file.unlink()
            except OSError as e:
                raise ConfigurationError(f"Cannot delete config file: {e}")

    def create_api_client(self, config: NautexConfig):
        """Create a nautex API client configured for the given config.

        Args:
            config: Configuration to create client for

        Returns:
            Configured NautexAPIClient
        """
        # Import the client here to avoid circular imports
        from ..api.client import NautexAPIClient
        import os

        # Use API host from config instead of hardcoded URL
        api_host = config.api_host
        return NautexAPIClient(api_host) 
