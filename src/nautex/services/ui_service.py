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


    # def launch_status(self):
    #     """Launch the status TUI."""
    #     from ..tui.screens import StatusScreen
    #     plan_context = self.plan_context_service.get_plan_context()
    #     app = StatusScreen(
    #         plan_context=plan_context,
    #         integration_status_service=self.integration_status_service
    #     )
    #     app.run()

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
        """Handle the status command by showing current integration status.

        Args:
            noui: If True, displays status as console output; if False, launches StatusScreen TUI
        """
        try:
            # Get the current plan context using injected service
            plan_context = await self.plan_context_service.get_plan_context()

            if noui:
                # Display as console output
                self._display_status_console(plan_context)
            else:
                # Launch TUI status screen
                await self._display_status_tui(plan_context)

        except Exception as e:
            if noui:
                print(f"❌ Error getting status: {e}")
            else:
                # For TUI errors, fall back to console
                print(f"TUI error, displaying console status: {e}")
                # Try to get basic status without full plan context
                print("Status: Error occurred while gathering status information")

    def _display_status_console(self, plan_context: PlanContext) -> None:
        """Display status information as formatted console output.

        Args:
            plan_context: The plan context data to display
        """
        print("\n=== Nautex CLI Status ===\n")

        # Configuration Status
        print("📋 Configuration:")
        if plan_context.config_summary:
            config = plan_context.config_summary
            print(f"   Agent Name: {config.get('agent_instance_name', 'Not set')}")
            print(f"   Project ID: {config.get('project_id', 'Not set')}")
            print(f"   Plan ID: {config.get('implementation_plan_id', 'Not set')}")
            print(f"   API Token: {'✅ Configured' if config.get('has_token') else '❌ Missing'}")
        else:
            print("   ❌ No configuration found")

        # API Status
        print(f"\n🌐 API Connectivity:")
        if plan_context.api_connected:
            latency_text = f" (latency: {plan_context.api_response_time:.3f}s)" if plan_context.api_response_time else ""
            print(f"   ✅ Connected{latency_text}")
            if hasattr(plan_context, 'account_info') and plan_context.account_info:
                print(f"   📧 Account: {plan_context.account_info.get('profile_email', 'Unknown')}")
        else:
            print(f"   ❌ Connection failed")

        # MCP Status
        print(f"\n🔌 MCP Integration:")
        mcp_status_emoji = {
            "OK": "✅",
            "NOT_FOUND": "❌", 
            "INVALID": "⚠️",
            "ERROR": "❌"
        }
        emoji = mcp_status_emoji.get(plan_context.mcp_status.value, "❓")
        print(f"   {emoji} Status: {plan_context.mcp_status.value}")
        if plan_context.mcp_config_path:
            print(f"   📁 Config: {plan_context.mcp_config_path}")

        # Next Task
        print(f"\n📋 Next Task:")
        if plan_context.next_task:
            task = plan_context.next_task
            print(f"   🎯 {task.task_designator}: {task.name}")
            print(f"   📝 {task.description}")
            print(f"   📊 Status: {task.status}")
        else:
            print("   ℹ️ No tasks available")

        # Advised Action
        print(f"\n💡 Recommended Action:")
        print(f"   {plan_context.advised_action}")

        print()

    async def _display_status_tui(self, plan_context: PlanContext) -> None:
        """Display status information using the StatusScreen TUI.

        Args:
            plan_context: The plan context data to display
        """
        # Use the injected integration status service
        from ..tui.screens import StatusScreen
        status_app = StatusScreen(
            plan_context, 
            integration_status_service=self.integration_status_service
        )
        await status_app.run_async()