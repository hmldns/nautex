"""UI Service for managing TUI applications and interactions."""

from typing import Optional
from pathlib import Path

from ..services.config_service import ConfigurationService
from ..services.integration_status_service import IntegrationStatusService
from ..services.nautex_api_service import NautexAPIService
from ..models.plan_context import PlanContext
from ..tui.screens import SetupApp


class UIService:
    """Service for managing TUI operations and screen orchestration."""

    def __init__(
        self, 
        config_service: ConfigurationService,
        integration_status_service: IntegrationStatusService,
        api_service: NautexAPIService,
        mcp_config_service=None,
        agent_rules_service=None,
    ):
        """Initialize the UI service.

        Args:
            config_service: Service for configuration management
            integration_status_service: Service for integration status management
            api_service: Service for API interactions
            mcp_config_service: Service for MCP configuration management
            agent_rules_service: Service for agent rules management
        """
        self.config_service = config_service
        self.integration_status_service = integration_status_service
        self.api_service = api_service
        self.mcp_config_service = mcp_config_service
        self.agent_rules_service = agent_rules_service

    async def handle_setup_command(self) -> None:
        """Handle the setup command by launching the interactive SetupScreen TUI.

        This method creates the SetupApp with all necessary services and runs it.
        The SetupApp will handle the full setup flow including:
        - Token input and validation
        - Agent name configuration
        - Project/plan selection
        - Configuration saving
        - MCP configuration check
        """
        try:
            # Create the setup app with the necessary services
            app = SetupApp(
                config_service=self.config_service,
                integration_status_service=self.integration_status_service,
                api_service=self.api_service,
                mcp_config_service=self.mcp_config_service,
                agent_rules_service=self.agent_rules_service
            )
            await app.run_async()

        except Exception as e:
            # If the TUI fails, fall back to a simple error message
            print(f"Setup failed: {e}")
            print("Please check your configuration and try again.")

        finally:
            # Ensure API client is closed even if an exception occurs
            # This prevents "Unclosed client session" errors when the app is terminated
            self.integration_status_service.stop_polling()
            await self.api_service.api_client.close()

    async def handle_status_command(self, noui: bool = False) -> None:
        print("Status Screen: Under development")
