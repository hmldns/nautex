"""Integration Status Service for managing API validation, config validation, and MCP status."""

import logging
import asyncio
from typing import Optional, Tuple, Dict, Any, Callable
from .config_service import ConfigurationService, ConfigurationError
from .nautex_api_service import NautexAPIService
from .mcp_config_service import MCPConfigService
from ..utils.mcp_utils import MCPConfigStatus
from .agent_rules_service import AgentRulesService

from ..models.integration_status import IntegrationStatus

# Set up logging
logger = logging.getLogger(__name__)


class IntegrationStatusService:

    def __init__(
        self,
        config_service: ConfigurationService,
        mcp_config_service: MCPConfigService,
        agent_rules_service: AgentRulesService,
        nautex_api_service: Optional[NautexAPIService],
    ):
        """Initialize the integration status service.

        Args:
            config_service: Service for configuration management
            mcp_config_service: Service for MCP configuration management
            agent_rules_service: Service for agent rules management
            nautex_api_service: Service for Nautex API operations (can be None if not configured)
            project_root: Root directory for the project
        """
        self.config_service = config_service
        self.mcp_config_service = mcp_config_service
        self.agent_rules_service = agent_rules_service
        self._nautex_api_service = nautex_api_service

        # Polling related attributes
        self._polling_task = None
        self._polling_interval = 5.0  # seconds
        self._on_update_callback = None

    async def get_integration_status(self) -> IntegrationStatus:
        """Get comprehensive integration status.

        Returns:
            IntegrationStatus object containing all integration health information
        """
        logger.debug("Gathering integration status...")

        # Initialize status
        status = IntegrationStatus(
            config=self.config_service.config
        )

        if status.config_loaded:

            await self._check_network_connectivity(status)
            await self._check_api_connectivity(status)
            await self._update_implementation_plan(status)

            if self.config_service.config.agent_type_selected:
                await self._check_mcp_status(status)
                self._check_agent_rules_status(status)

        return status

    async def _check_mcp_status(self, status: IntegrationStatus) -> None:
        """Check MCP integration status."""
        logger.debug("Checking MCP configuration...")
        status.mcp_status, status.mcp_config_path = await self.mcp_config_service.check_mcp_configuration()
        logger.debug(f"MCP status: {status.mcp_status}, path: {status.mcp_config_path}")

    def _check_agent_rules_status(self, status: IntegrationStatus) -> None:
        """Check agent rules status."""
        logger.debug("Checking agent rules...")
        status.agent_rules_status, status.agent_rules_path = self.agent_rules_service.validate_rules()
        logger.debug(f"Agent rules status: {status.agent_rules_status}, path: {status.agent_rules_path}")

    async def _check_network_connectivity(self, status: IntegrationStatus) -> None:
        """Test network connectivity to API host with short timeout."""

        try:
            logger.debug("Testing network connectivity...")

            network_ok, response_time, error_msg = await self._nautex_api_service.check_network_connectivity(timeout=5.0)

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
            # logger.warning(f"API connectivity check failed: {e}")
            status.api_connected = False
            status.api_response_time = None

    async def _update_implementation_plan(self, status: IntegrationStatus):
        """Update the implementation plan."""
        try:
            if self.config_service.config.plan_id:
                plan = await self._nautex_api_service.get_implementation_plan(status.config.project_id, status.config.plan_id)
                status.implementation_plan = plan

        except Exception:
            raise

    def start_polling(self, on_update: Optional[Callable[[IntegrationStatus], None]] = None, interval: Optional[float] = None) -> None:
        """Start a background task to poll for integration status updates.

        Args:
            on_update: Optional callback function to be called when new status is available
            interval: Optional polling interval in seconds (defaults to self._polling_interval)
        """
        if interval is not None:
            self._polling_interval = interval

        self._on_update_callback = on_update

        if self._polling_task is None:
            self._polling_task = asyncio.create_task(self._poll_integration_status())
            logger.debug("Started integration status polling task")

    def stop_polling(self) -> None:
        """Stop the polling task if it's running."""
        if self._polling_task is not None:
            self._polling_task.cancel()
            self._polling_task = None
            logger.debug("Stopped integration status polling task")

    async def _poll_integration_status(self) -> None:
        """Continuously poll for integration status updates."""
        try:
            while True:
                await asyncio.sleep(self._polling_interval)

                try:
                    status = await self.get_integration_status()

                    # Call the callback if provided
                    if self._on_update_callback:
                        self._on_update_callback(status)

                except Exception as e:
                    logger.error(f"Error getting integration status: {e}")

        except asyncio.CancelledError:
            # Task was cancelled, clean up
            logger.debug("Integration status polling task cancelled")
        except Exception as e:
            logger.error(f"Error in integration status polling: {e}")
            # Attempt to restart polling after a brief delay
            await asyncio.sleep(1.0)
            self.start_polling(self._on_update_callback)
