"""TUI screen for displaying application status."""

import asyncio
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Static, Header, Footer

from ..widgets import (
    IntegrationStatusWidget,
    PlanContextWidget,
)
from ...services.integration_status_service import (
    IntegrationStatusService,
)
from ...models.integration_status import IntegrationStatus


class StatusScreen(App):
    """TUI application for displaying current status and configuration."""

    CSS = """
    #title {
        text-align: center;
        background: $primary;
        color: $text;
        padding: 1;
        margin: 0 0 1 0;
    }

    #main_content {
        padding: 1;
        margin: 0;
    }

    .section_header {
        color: $primary;
        margin: 1 0 0 0;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
    ]

    def __init__(
        self,
        plan_context,
        integration_status_service: IntegrationStatusService = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.plan_context = plan_context
        self.integration_status_service = integration_status_service
        self.integration_status_widget = IntegrationStatusWidget()
        self.plan_context_widget = PlanContextWidget()

        # Task for polling integration status
        self._polling_task = None
        self._polling_interval = 5.0  # seconds

    def compose(self) -> ComposeResult:
        """Compose the status screen layout."""
        yield Header()

        with Vertical(id="main_content"):
            yield self.integration_status_widget
            yield self.plan_context_widget
            yield Static("Configuration", classes="section_header")
            if self.plan_context.config_summary:
                config = self.plan_context.config_summary
                yield Static(f"Agent: {config.get('agent_instance_name', 'Not set')}")
                yield Static(f"Project: {config.get('project_id', 'Not set')}")
                yield Static(f"Plan: {config.get('implementation_plan_id', 'Not set')}")
                yield Static(
                    f"Token: {'✅ Set' if config.get('has_token') else '❌ Missing'}"
                )
            else:
                yield Static("❌ No configuration found")

            yield Static("MCP Integration", classes="section_header")
            mcp_status_emoji = {
                "OK": "✅",
                "NOT_FOUND": "❌",
                "INVALID": "⚠️",
                "ERROR": "❌",
            }
            emoji = mcp_status_emoji.get(self.plan_context.mcp_status.value, "❓")
            yield Static(f"{emoji} {self.plan_context.mcp_status.value}")
            if self.plan_context.mcp_config_path:
                yield Static(f"Config: {self.plan_context.mcp_config_path}")

            yield Static("Next Task", classes="section_header")
            if self.plan_context.next_task:
                task = self.plan_context.next_task
                yield Static(f"🎯 {task.task_designator}: {task.name}")
                yield Static(f"{task.description}")
                yield Static(f"Status: {task.status}")
            else:
                yield Static("ℹ️ No tasks available")

            yield Static("Action", classes="section_header")
            yield Static(f"{self.plan_context.advised_action}")

        yield Footer()

    async def on_mount(self) -> None:
        """Called when the screen is mounted."""
        if self.integration_status_service:
            try:
                status = await self.integration_status_service.get_integration_status()
                self.integration_status_widget.update_from_integration_status(status)
            except Exception:
                self._update_from_plan_context()
        else:
            self._update_from_plan_context()

        self.plan_context_widget.update_from_plan_context(self.plan_context)

        # Start polling for integration status updates if service is available
        if self.integration_status_service:
            self._start_polling_integration_status()

    async def on_unmount(self) -> None:
        """Called when the screen is unmounted."""
        # Stop polling when screen is unmounted
        self._stop_polling_integration_status()

    def _start_polling_integration_status(self) -> None:
        """Start a background task to poll for integration status updates."""
        if self._polling_task is None:
            self._polling_task = asyncio.create_task(self._poll_integration_status())

    def _stop_polling_integration_status(self) -> None:
        """Stop the polling task if it's running."""
        if self._polling_task is not None:
            self._polling_task.cancel()
            self._polling_task = None

    async def _poll_integration_status(self) -> None:
        """Continuously poll for integration status updates."""
        try:
            while True:
                await asyncio.sleep(self._polling_interval)
                if self.integration_status_service:
                    try:
                        status = await self.integration_status_service.get_integration_status()
                        self.integration_status_widget.update_from_integration_status(status)
                    except Exception:
                        # If there's an error, fall back to plan context data
                        self._update_from_plan_context()
        except asyncio.CancelledError:
            # Task was cancelled, clean up
            pass
        except Exception as e:
            self.log(f"Error in integration status polling: {e}")
            # Attempt to restart polling after a brief delay
            await asyncio.sleep(1.0)
            self._start_polling_integration_status()

    def _update_from_plan_context(self) -> None:
        """Update integration status widget from plan context data."""
        status = IntegrationStatus(
            config_loaded=self.plan_context.config_loaded,
            config_path=self.plan_context.config_path,
            config_summary=self.plan_context.config_summary,
            api_connected=self.plan_context.api_connected,
            api_response_time=self.plan_context.api_response_time,
            account_info=getattr(self.plan_context, "account_info", None),
            mcp_status=self.plan_context.mcp_status,
            mcp_config_path=self.plan_context.mcp_config_path,
            integration_ready=bool(self.plan_context.next_task),
            status_message=self.plan_context.advised_action,
        )
        self.integration_status_widget.update_from_integration_status(status)

    def action_quit(self) -> None:
        """Quit the application."""
        self.exit() 
