"""UI Service for managing TUI applications and interactions."""

from typing import Optional
from pathlib import Path

from ..services.config_service import ConfigurationService
from ..services.plan_context_service import PlanContextService
from ..services.integration_status_service import IntegrationStatusService
from ..services.nautex_api_service import NautexAPIService
from ..models.plan_context import PlanContext
from ..tui.screens import SetupApp


class UIService:
    """Service for managing TUI operations and screen orchestration."""

    def __init__(
        self, 
        config_service: ConfigurationService,
        plan_context_service: PlanContextService,
        integration_status_service: IntegrationStatusService,
        api_service: NautexAPIService,
        project_root: Optional[Path] = None
    ):
        """Initialize the UI service.

        Args:
            config_service: Service for configuration management
            plan_context_service: Service for plan context management
            integration_status_service: Service for integration status management
            project_root: Root directory for the project. Defaults to current working directory.
        """
        self.project_root = project_root or Path.cwd()
        self.config_service = config_service
        self.plan_context_service = plan_context_service
        self.integration_status_service = integration_status_service
        self.api_service = api_service

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
                project_root=self.project_root,
                integration_status_service=self.integration_status_service,
                api_service=self.api_service
            )
            await app.run_async()

        except Exception as e:
            # If the TUI fails, fall back to a simple error message
            print(f"Setup failed: {e}")
            print("Please check your configuration and try again.")

    async def handle_status_command(self, noui: bool = False) -> None:
        print("Status Screen: Under development")
