"""TUI screen for the interactive setup process."""

import asyncio
from pathlib import Path
from typing import Optional

from pydantic import SecretStr
from pygments.styles.dracula import yellow
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Static

from ..widgets import (
    ValidatedTextInput,
    IntegrationStatusWidget,
    LoadableList,
    SystemInfoWidget,
)
from ...services.config_service import ConfigurationService, ConfigurationError
from ...services.integration_status_service import IntegrationStatusService
from ...services.mcp_config_service import MCPConfigService
from ...services.nautex_api_service import NautexAPIService
from ...models.config_models import NautexConfig


class SetupScreen(Screen):
    """Interactive setup screen for configuring the Nautex CLI."""

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
        Binding("tab", "next_input", "Next Field"),
        Binding("enter", "next_input", "Next Field"),
    ]

    CSS = """
    #status_section {
        height: auto;
        margin: 0;
        padding: 0 1;         /* match main content padding for alignment */
    }

    #system_info_section {
        height: auto;
        margin: 0;
        padding: 0 1;         /* match main content padding for alignment */
    }

    #main_content {
        padding: 1;
        margin: 0;
        height: 1fr;           /* occupy remaining vertical space */
    }

    #input_and_sysinfo {
        height: 15;            /* fixed height to leave space for lists */
        margin-bottom: 0;
    }

    #loadable_lists_container {
        height: 1fr;           /* take all remaining space */
        margin: 0;
        padding: 0;
        min-height: 10;        /* ensure lists are visible */
    }

    #loadable_lists_container > LoadableList {
        width: 1fr;           /* even horizontal distribution */
        height: 1fr;          /* fill vertical space */
        margin-right: 1;
    }

    #loadable_lists_container > LoadableList:last-of-type {
        margin-right: 0;
    }

    #toggle_button, #reload_button {
        margin: 1 0;
        width: auto;
        height: 1fr;
    }

    #reload_button {
        background: $success;
    }
    """

    def __init__(
        self,
        config_service: ConfigurationService,
        project_root: Path,
        integration_status_service: IntegrationStatusService,
        api_service: NautexAPIService,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.config_service = config_service
        self.project_root = project_root
        self.integration_status_service = integration_status_service
        self.api_service = api_service

        # Task for polling integration status
        self._polling_task = None
        self._polling_interval = 5.0  # seconds

        # Setup state
        self.setup_data = {}

        # Create API token link (using Static with markup instead of Link)
        api_token_link = Static("[link=https://app.nautex.ai/new_token](app.nautex.ai/new_token)[/link]", markup=True)

        # Widget references
        self.integration_status_widget = IntegrationStatusWidget()
        self.system_info_widget = SystemInfoWidget()
        self.api_token_input = ValidatedTextInput(
            title="API Token",
            placeholder="Enter your Nautex.ai API token...",
            validator=self.validate_api_token,
            title_extra=api_token_link,
            on_change=self.set_token
        )
        self.agent_name_input = ValidatedTextInput(
            title="Agent Instance Name",
            placeholder="e.g., my-dev-agent",
            default_value="My Agent",
            validator=self.validate_agent_name,
            on_change=self.set_agent_name
        )

        # ------------------------------------------------------------------
        # Data loaders for the two lists - with mock data and artificial delays
        # ------------------------------------------------------------------

        async def list1_loader() -> list[str]:
            """Return demo data for List 1 asynchronously with artificial delay."""
            # Simulate network delay or processing time
            await asyncio.sleep(1.0)  # 1 second delay for testing

            # Mock data that would normally come from an API or database
            mock_data = ["Loaded 1", "Loaded 2", "Loaded 3", "Item A", "Item B", "Item C"]
            return mock_data

        async def list2_loader() -> list[str]:
            """Return demo data for List 2 asynchronously with artificial delay, appending currently selected item from List 1 if available."""
            # Simulate network delay or processing time (slightly longer than list1)
            await asyncio.sleep(1.5)  # 1.5 second delay for testing

            # Mock data that would normally come from an API or database
            mock_data = ["Data 1", "Data 2", "Data 3"]

            # Add the selected item from list1 if available
            selected = self.loadable_list1.selected_item if hasattr(self, "loadable_list1") else None
            if selected:
                mock_data.append(f"Selected from List 1: {selected}")

            return mock_data

        # Create loadable list widgets
        self.loadable_list1 = LoadableList(
            title="Projects",
            data_loader=list1_loader,
            on_change=self.on_list1_selection_change,
        )

        # For List 2 we provide the loader that references the first list's
        # selection so it can include it on each reload.
        self.loadable_list2 = LoadableList(
            title="Implementation plans",
            data_loader=list2_loader,
            on_change=self.on_list2_selection_change,
        )

        # Create a button to enable/disable the first list (toggles label)
        self.toggle_button = Button("Disable List 1", id="toggle_button")
        self.toggle_button.on_click = self.on_toggle_button_click

        # Create a button to reload both lists
        self.reload_button = Button("Reload Lists", id="reload_button")
        self.reload_button.on_click = self.on_reload_button_click

        # Create a list of focusable widgets for tab/enter navigation
        self.focusable_widgets = [
            self.api_token_input,
            self.agent_name_input,
            self.loadable_list1,
            self.loadable_list2,
            # self.toggle_button,
            # self.reload_button,
        ]
        self.current_focus_index = 0

        self._load_existing_config()


    async def validate_api_token(self, value: str) -> tuple[bool, str]:
        """Validate the API token."""
        if not value.strip():
            return False, "API token is required"
        if len(value.strip()) < 8:
            return False, "API token must be at least 8 characters"

        try:
            acc_info = await self.api_service.get_account_info(token_override=value, timeout=1.0)
            self.system_info_widget.update_system_info(
                email=acc_info.profile_email,
            )
            return True, ""
        except Exception as e:
            return False, f"{e}"

    async def validate_agent_name(self, value: str) -> tuple[bool, str]:
        """Validate the agent name."""
        if not value.strip():
            return False, "Agent name is required"
        return True, ""

    async def set_token(self, token: str) -> None:
        self.config_service.config.api_token = SecretStr(token)
        self.config_service.save_configuration()

    async def set_agent_name(self, name: str) -> None:
        self.config_service.config.agent_instance_name = name
        self.config_service.save_configuration()

    def compose(self) -> ComposeResult:
        with Vertical(id="status_section"):
            yield self.integration_status_widget
        # with Vertical(id="system_info_section"):
        #     yield self.system_info_widget
        with Vertical(id="main_content"):
            with Horizontal(id="input_and_sysinfo"):
                with Vertical(id="input_section"):
                    yield self.api_token_input
                    yield self.agent_name_input
                    # Add toggle button and reload button
                    # yield self.toggle_button
                    # yield self.reload_button
                    # yield self.refresh_system_info_button
                    # Add loadable lists side by side in a horizontal container

                yield self.system_info_widget

            with Horizontal(id="loadable_lists_container"):
                yield self.loadable_list1
                yield self.loadable_list2

        yield Footer()

    async def on_mount(self) -> None:
        await self._update_integration_status()
        await self._update_system_info()
        self.api_token_input.focus()

        # Start polling for integration status updates
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
                await self._update_integration_status()
        except asyncio.CancelledError:
            # Task was cancelled, clean up
            pass
        except Exception as e:
            self.app.log(f"Error in integration status polling: {e}")
            # Attempt to restart polling after a brief delay
            await asyncio.sleep(1.0)
            self._start_polling_integration_status()

    def _load_existing_config(self) -> None:
        self.api_token_input.set_value(str(self.config_service.config.api_token))
        self.agent_name_input.set_value(str(self.config_service.config.agent_instance_name))

    def action_quit(self) -> None:
        self.app.exit()

    def action_next_input(self) -> None:
        """Move focus to the next input field."""
        if not self.focusable_widgets:
            return

        # Move to the next widget in the list
        self.current_focus_index = (self.current_focus_index + 1) % len(self.focusable_widgets)

        # Focus the next widget
        self.focusable_widgets[self.current_focus_index].focus()


    async def _update_integration_status(self) -> None:
        try:
            status = await self.integration_status_service.get_integration_status()

            self.integration_status_widget.update_from_integration_status(status)
            self.system_info_widget.update_system_info(
                email=status.account_info.profile_email if status.account_info else None,
                network_delay=status.network_response_time
            )

        except Exception:
            pass

    async def _update_system_info(self) -> None:
        """Update the system info widget with current data."""
        self.system_info_widget.update_system_info(
            host=self.config_service.config.api_host
        )

    async def on_toggle_button_click(self) -> None:
        """Enable or disable List 1 based on its current state."""
        if self.loadable_list1.is_disabled:
            self.loadable_list1.enable()
            self.toggle_button.label = "Disable List 1"
        else:
            self.loadable_list1.disable()
            self.toggle_button.label = "Enable List 1"

        # Reload List 1 so the UI updates accordingly (shows disabled msg if needed)
        self.loadable_list1.reload()

    async def on_list1_selection_change(self, selected_item: str) -> None:
        """Handle selection change in the first list."""
        self.app.log(f"List 1 selection changed: {selected_item}")
        # Refresh List 2 so it can include the latest selection in its data
        self.loadable_list2.reload()

    async def on_list2_selection_change(self, selected_item: str) -> None:
        """Handle selection change in the second list."""
        self.app.log(f"List 2 selection changed: {selected_item}")
        # You can add your own logic here to handle the selection change

    async def on_reload_button_click(self) -> None:
        """Reload both lists."""
        self.app.log("Reloading lists...")
        self.loadable_list1.reload()
        self.loadable_list2.reload()


class SetupApp(App):
    """TUI application for the setup command."""

    def __init__(self,
                 config_service: ConfigurationService,
                 project_root: Path,
                 api_service: NautexAPIService,
                 integration_status_service: IntegrationStatusService, **kwargs):
        super().__init__(**kwargs)
        self.config_service = config_service
        self.project_root = project_root
        self.api_service = api_service
        self.integration_status_service = integration_status_service

    def on_mount(self) -> None:
        """Called when the app starts."""
        mcp_config_service = MCPConfigService()
        setup_screen = SetupScreen(
            config_service=self.config_service,
            project_root=self.project_root,
            integration_status_service=self.integration_status_service,
            api_service=self.api_service,
        )
        self.push_screen(setup_screen)
