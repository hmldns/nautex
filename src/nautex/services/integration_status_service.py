"""Integration Status Service for managing API validation, config validation, and MCP status."""

import time
import logging
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any
from pathlib import Path

from ..models.config_models import NautexConfig, AccountInfo
from .config_service import ConfigurationService, ConfigurationError
from .nautex_api_service import NautexAPIService
from .mcp_config_service import MCPConfigService, MCPConfigStatus
from ..api.client import NautexAPIError

# Set up logging
logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class IntegrationStatus:
    """Data class representing current integration status."""

    config_loaded: bool = False
    config_path: Optional[Path] = None
    config_summary: Optional[Dict[str, Any]] = None
    api_connected: bool = False
    api_response_time: Optional[float] = None
    account_info: Optional[AccountInfo] = None
    mcp_status: MCPConfigStatus = MCPConfigStatus.NOT_FOUND
    mcp_config_path: Optional[Path] = None
    integration_ready: bool = False
    status_message: str = ""


class IntegrationStatusService:
    """Service for managing all integration status concerns.

    This service is the top-level integration point for:
    - API validation and connectivity testing
    - Configuration validation and management
    - MCP integration status checking
    - Overall integration health assessment
    """

    def __init__(
        self,
        config_service: ConfigurationService,
        mcp_config_service: MCPConfigService,
        nautex_api_service: Optional[NautexAPIService] = None,
        project_root: Optional[Path] = None
    ):
        """Initialize the integration status service.

        Args:
            config_service: Service for configuration management
            mcp_config_service: Service for MCP configuration management
            nautex_api_service: Service for Nautex API operations (can be None if not configured)
            project_root: Root directory for the project
        """
        self.config_service = config_service
        self.mcp_config_service = mcp_config_service
        self.project_root = project_root or Path.cwd()
        self._nautex_api_service = nautex_api_service

    async def get_integration_status(self) -> IntegrationStatus:
        """Get comprehensive integration status.

        Returns:
            IntegrationStatus object containing all integration health information
        """
        logger.debug("Gathering integration status...")

        # Initialize status
        status = IntegrationStatus()

        # 1. Check configuration
        await self._check_configuration_status(status)

        # 2. Check MCP integration
        self._check_mcp_status(status)

        # 3. Test API connectivity (if config is available)
        if status.config_loaded:
            await self._check_api_connectivity(status)

        # 4. Determine overall integration readiness
        self._determine_integration_readiness(status)

        logger.info(f"Integration status: {status.status_message}")
        return status

    async def validate_api_token(self, token: str, api_client_factory=None) -> Tuple[bool, Optional[AccountInfo], Optional[str]]:
        """Validate an API token without requiring full configuration.

        Args:
            token: API token to validate
            api_client_factory: Function to create API client (if None, uses default)

        Returns:
            Tuple of (is_valid, account_info, error_message)
        """
        try:
            from pydantic import SecretStr
            import os

            # Create temporary config for validation
            temp_config = NautexConfig(
                agent_instance_name="validation-temp",
                api_token=SecretStr(token)
            )

            # Create API client using factory or default
            if api_client_factory is None:
                from ..api import create_api_client
                # Check for test mode from environment or config default
                test_mode = os.getenv('NAUTEX_API_TEST_MODE', 'true').lower() == 'true'
                api_client = create_api_client(base_url="https://api.nautex.ai", test_mode=test_mode)
            else:
                api_client = api_client_factory()

            # Create temporary service for validation
            api_service = NautexAPIService(api_client, temp_config)

            # Test the token
            account_info = await api_service.verify_token_and_get_account_info()
            return True, account_info, None

        except NautexAPIError as e:
            logger.warning(f"API token validation failed: {e}")
            return False, None, str(e)
        except Exception as e:
            logger.error(f"Unexpected error during token validation: {e}")
            return False, None, f"Unexpected error: {str(e)}"

    def validate_configuration_completeness(self, config: NautexConfig) -> Tuple[bool, str]:
        """Validate if configuration has all required fields for operation.

        Args:
            config: Configuration to validate

        Returns:
            Tuple of (is_complete, status_message)
        """
        if not config.api_token:
            return False, "API token is required"

        if not config.agent_instance_name:
            return False, "Agent instance name is required"

        if not config.project_id:
            return False, "Project ID must be selected"

        if not config.implementation_plan_id:
            return False, "Implementation plan must be selected"

        return True, "Configuration is complete"

    async def _check_configuration_status(self, status: IntegrationStatus) -> None:
        """Check configuration loading and validity."""
        try:
            logger.debug("Loading configuration...")
            config = self.config_service.load_configuration()
            status.config_loaded = True
            status.config_path = self.config_service.get_config_path()
            status.config_summary = self._create_config_summary(config)

            logger.debug(f"Configuration loaded from {status.config_path}")

        except ConfigurationError as e:
            logger.warning(f"Failed to load configuration: {e}")
            status.config_loaded = False

    def _check_mcp_status(self, status: IntegrationStatus) -> None:
        """Check MCP integration status."""
        logger.debug("Checking MCP configuration...")
        status.mcp_status, status.mcp_config_path = self.mcp_config_service.check_mcp_configuration()
        logger.debug(f"MCP status: {status.mcp_status}, path: {status.mcp_config_path}")

    async def _check_api_connectivity(self, status: IntegrationStatus) -> None:
        """Test API connectivity and get account information."""
        if not self._nautex_api_service or not status.config_summary:
            return

        try:
            logger.debug("Testing API connectivity...")
            start_time = time.time()

            # Test connectivity with account info fetch
            status.account_info = await self._nautex_api_service.verify_token_and_get_account_info()
            status.api_response_time = time.time() - start_time
            status.api_connected = True

            logger.debug(f"API connectivity verified in {status.api_response_time:.3f}s")

        except NautexAPIError as e:
            logger.warning(f"API connectivity test failed: {e}")
            status.api_connected = False
            status.api_response_time = None

    def _determine_integration_readiness(self, status: IntegrationStatus) -> None:
        """Determine overall integration readiness and status message."""
        # Priority 1: Configuration issues
        if not status.config_loaded:
            status.integration_ready = False
            status.status_message = "Configuration not found - run 'nautex setup'"
            return

        # Priority 2: API connectivity issues  
        if not status.api_connected:
            status.integration_ready = False
            status.status_message = "API connectivity failed - check token and network"
            return

        # Priority 3: Missing project/plan configuration
        if not status.config_summary or not status.config_summary.get("project_id"):
            status.integration_ready = False
            status.status_message = "Project not selected - run 'nautex setup'"
            return

        if not status.config_summary.get("plan_id"):
            status.integration_ready = False
            status.status_message = "Implementation plan not selected - run 'nautex setup'"
            return

        # Integration is ready for work
        status.integration_ready = True
        if status.mcp_status != MCPConfigStatus.OK:
            status.status_message = "Ready to work (consider setting up MCP integration for IDE support)"
        else:
            status.status_message = "Fully integrated and ready to work"

    def _create_config_summary(self, config: NautexConfig) -> Dict[str, Any]:
        """Create a summary of the configuration.

        Args:
            config: The loaded configuration

        Returns:
            Dictionary summary of key configuration fields
        """
        return {
            "agent_instance_name": config.agent_instance_name,
            "project_id": config.project_id,
            "plan_id": config.implementation_plan_id,
            "has_token": bool(config.api_token)
        }

    def get_nautex_api_service(self) -> Optional[NautexAPIService]:
        """Get the configured Nautex API service if available.

        Returns:
            NautexAPIService instance or None if not configured
        """
        return self._nautex_api_service 
