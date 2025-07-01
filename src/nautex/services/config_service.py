"""Configuration service for loading and saving Nautex CLI settings."""

import json
import os
import stat
import platform
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import ValidationError

from ..models.config_models import NautexConfig


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

        self._config: Optional[NautexConfig] = None

    @property
    def config(self) -> NautexConfig:
        return self._config

    @property
    def cwd(self) -> Path :
        return Path.cwd()

    @property
    def nautex_dir(self):
        return Path(".nautex")

    @property
    def documents_path(self) -> Path :
        if self.config.documents_path:
            return Path(self.config.documents_path)
        else:
            return self.nautex_dir / "docs"

    def load_configuration(self) -> NautexConfig:
        """Load configuration from .nautex/config.json and environment variables.

        The configuration is loaded with the following precedence:
        1. Environment variables (with NAUTEX_ prefix)
        2. .env file in project root
        3. .nautex/config.json file
        4. Default values from the model

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

            # Remove account_details if present (no longer part of NautexConfig)
            if 'account_details' in merged_config:
                merged_config.pop('account_details')

            # Create NautexConfig with merged data
            # pydantic-settings will also automatically check for env vars with NAUTEX_ prefix
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

    def _load_environment_variables(self) -> Dict[str, Any]:
        """Load environment variables with NAUTEX_ prefix.

        Returns:
            Dict with environment variable values (keys without NAUTEX_ prefix)
        """
        env_vars = {}
        prefix = "NAUTEX_"

        # Check for environment variables with NAUTEX_ prefix
        for key, value in os.environ.items():
            if key.startswith(prefix):
                # Remove prefix and convert to lowercase for pydantic field matching
                field_name = key[len(prefix):].lower()

                # Handle boolean values
                if field_name == "api_test_mode":
                    env_vars[field_name] = value.lower() in ("true", "1", "yes", "on")
                else:
                    env_vars[field_name] = value

        # Load from .env file if it exists (lower precedence than system env vars)
        if self.env_file.exists():
            try:
                with open(self.env_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")  # Remove quotes

                            if key.startswith(prefix):
                                field_name = key[len(prefix):].lower()
                                # Only use .env value if not already set by system env var
                                if field_name not in env_vars:
                                    if field_name == "api_test_mode":
                                        env_vars[field_name] = value.lower() in ("true", "1", "yes", "on")
                                    else:
                                        env_vars[field_name] = value
            except IOError:
                # If we can't read .env file, just continue without it
                pass

        return env_vars

    def save_configuration(self, config_data: Optional[NautexConfig] = None) -> None:
        if config_data is None:
            config_data = self._config

        try:
            # Ensure .nautex directory exists
            self.config_dir.mkdir(exist_ok=True)

            # Convert config to dict, handling SecretStr and nested models
            config_dict = self._prepare_config_for_saving(config_data)

            # Write JSON to file
            try:
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(config_dict, f, indent=2, ensure_ascii=False)
            except IOError as e:
                raise ConfigurationError(f"Cannot write config file: {e}")

            # Set file permissions (user read/write only)
            self._set_secure_file_permissions(self.config_file)

        except Exception as e:
            if isinstance(e, ConfigurationError):
                raise
            raise ConfigurationError(f"Unexpected error saving configuration: {e}")

    def _prepare_config_for_saving(self, config_data: NautexConfig) -> Dict[str, Any]:
        config_dict = config_data.model_dump(exclude_none=True)

        # Handle SecretStr fields - extract the actual secret value for storage
        if 'api_token' in config_dict:
            config_dict['api_token'] = config_data.api_token.get_secret_value()

        return config_dict

    def _set_secure_file_permissions(self, file_path: Path) -> None:
        """Set secure file permissions on the configuration file.

        Sets permissions to user read/write only (600 on Unix-like systems).
        On Windows, uses os.chmod if available, otherwise relies on default ACLs.

        Args:
            file_path: Path to the file to secure
        """
        try:
            if platform.system() in ('Linux', 'Darwin'):  # Unix-like systems
                # Set permissions to 600 (user read/write only)
                os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR)
            elif platform.system() == 'Windows':
                # On Windows, try to set restrictive permissions
                # This is a best-effort approach
                try:
                    # Remove read access for group and others
                    os.chmod(file_path, stat.S_IREAD | stat.S_IWRITE)
                except (OSError, AttributeError):
                    # If chmod doesn't work on Windows, the default ACLs should be reasonably secure
                    pass
        except Exception:
            # If we can't set permissions, log a warning but don't fail
            # In production, this might warrant a warning log
            pass

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
