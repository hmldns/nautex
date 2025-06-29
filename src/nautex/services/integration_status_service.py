"""Integration Status Service for managing API validation, config validation, and MCP status."""

import time
import logging
from typing import Optional, Tuple, Dict, Any
from pathlib import Path

from ..models.config_models import NautexConfig
from .config_service import ConfigurationService, ConfigurationError
from .nautex_api_service import NautexAPIService
from .mcp_config_service import MCPConfigService, MCPConfigStatus
from ..api.client import NautexAPIError
from ..models.integration_status import IntegrationStatus

# Set up logging
logger = logging.getLogger(__name__)


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
        nautex_api_service: Optional[NautexAPIService],
        project_root: Optional[Path]
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

        # 3. Test network connectivity first (quick check)
        # if status.config_loaded:
        await self._check_network_connectivity(status)

        await self._check_api_connectivity(status)

        # 5. Determine overall integration readiness
        self._determine_integration_readiness(status)

        logger.info(f"Integration status: {status.status_message}")
        return status


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

        if not config.plan_id:
            return False, "Implementation plan must be selected"

        return True, "Configuration is complete"

    async def _check_configuration_status(self, status: IntegrationStatus) -> None:
        """Check configuration loading and validity."""
        try:
            logger.debug("Loading configuration...")
            config = self.config_service.load_configuration()
            status.config_loaded = True
            status.config_path = self.config_service.get_config_path()



            logger.debug(f"Configuration loaded from {status.config_path}")

        except ConfigurationError as e:
            logger.warning(f"Failed to load configuration: {e}")
            status.config_loaded = False

    def _check_mcp_status(self, status: IntegrationStatus) -> None:
        """Check MCP integration status."""
        logger.debug("Checking MCP configuration...")
        status.mcp_status, status.mcp_config_path = self.mcp_config_service.check_mcp_configuration()
        logger.debug(f"MCP status: {status.mcp_status}, path: {status.mcp_config_path}")

    async def _check_network_connectivity(self, status: IntegrationStatus) -> None:
        """Test network connectivity to API host with short timeout."""

        try:
            logger.debug("Testing network connectivity...")
            
            # Quick network connectivity check with 3 second timeout
            network_ok, response_time, error_msg = await self._nautex_api_service.check_network_connectivity(timeout=1.0)
            
            # Store network status as a custom attribute
            status.network_connected = network_ok
            status.network_response_time = response_time
            status.network_error = error_msg

            if network_ok:
                logger.debug(f"Network connectivity verified in {response_time:.3f}s")
            else:
                logger.warning(f"Network connectivity failed: {error_msg}")

        except Exception as e:
            logger.warning(f"Network connectivity check failed: {e}")
            status.network_connected = False
            status.network_response_time = None
            status.network_error = str(e)

    async def _check_api_connectivity(self, status: IntegrationStatus) -> None:
        """Test API connectivity with a longer timeout."""
        try:
            logger.debug("Testing API connectivity...")
            acc_info = await self._nautex_api_service.get_account_info(timeout=5.0)
            status.api_connected = bool(acc_info)
            status.account_info = acc_info
        except Exception as e:
            logger.warning(f"API connectivity check failed: {e}")
            status.api_connected = False
            status.api_response_time = None

    def _determine_integration_readiness(self, status: IntegrationStatus) -> None:
        """Determine overall integration readiness and status message."""
        # Priority 1: Configuration issues
        if not status.config_loaded:
            status.integration_ready = False
            status.status_message = "Configuration not found - run 'nautex setup'"
            return

        # Priority 2: Network connectivity issues
        if hasattr(status, 'network_connected') and not status.network_connected:
            status.integration_ready = False
            status.status_message = f"Network connectivity failed - check connection to {getattr(status, 'network_error', 'API host')}"
            return

        # Priority 3: API connectivity issues  
        if not status.api_connected:
            status.integration_ready = False
            status.status_message = "API connectivity failed - check token and API host"
            return

        # Priority 4: Missing project/plan configuration
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
            "plan_id": config.plan_id,
            "has_token": bool(config.api_token)
        }
