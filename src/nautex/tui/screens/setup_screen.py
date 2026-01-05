"""TUI screen for the interactive setup process."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from pydantic import SecretStr
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Static, Link

from ..widgets import (
    ValidatedTextInput,
    IntegrationStatusWidget,
    LoadableList,
    SystemInfoWidget,
)
from ..widgets.config_dialogs import MCPConfigWriteDialog, AgentRulesWriteDialog, AgentSelectionDialog
from ..widgets.info_help_dialog import InfoHelpDialog
from ...models.integration_status import IntegrationStatus
from ...services.config_service import ConfigurationService, ConfigurationError
from ...services.integration_status_service import IntegrationStatusService
from ...services.mcp_config_service import MCPConfigService, MCPConfigStatus
from ...services.agent_rules_service import AgentRulesService
from ...agent_setups.base import AgentRulesStatus
from ...services.nautex_api_service import NautexAPIService
from ...models.config import NautexConfig
from ...utils import path2display


@dataclass(kw_only=True)
class ProjectItem:
    id: str
    name: str

    def __str__(self):
        return self.name

@dataclass(kw_only=True)
class ImplementationPlanItem:
    id: str
    name: str

    def __str__(self):
        return self.name


class SetupScreen(Screen):
    """Interactive setup screen for configuring the Nautex CLI."""

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
        Binding("tab", "next_input", "Next Field"),
        Binding("enter", "next_input", "Next Field"),
        Binding("ctrl+y", "show_agent_selection_dialog", "Select Agent Type"),
        Binding("ctrl+t", "show_mcp_dialog", "MCP Config"),
        Binding("ctrl+r", "show_agent_rules_dialog", "Agent Rules"),
        Binding("f1", "show_info_help", "Info & Help"),
    ]

    CSS = """
    #header {
        height: auto;
        padding: 0;
        background: $primary-darken-2;
        color: $text;
        text-style: bold;
        margin: 0 0 1 0;
        text-align: center;
    }

    #environment_info {
        height: auto;
        padding: 0 1;
        margin: 1 0 0 0;
        color: $text;
        text-align: right;
    }

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
        integration_status_service: IntegrationStatusService,
        api_service: NautexAPIService,
        mcp_config_service: MCPConfigService,
        agent_rules_service: AgentRulesService,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.config_service = config_service
        self.integration_status_service = integration_status_service
        self.api_service = api_service
        self.mcp_config_service = mcp_config_service
        self.agent_rules_service = agent_rules_service

        # Setup state
        self.setup_data = {}

        # Create API token link (using Static with markup instead of Link)
        api_token_link = Link("Get API token from: app.nautex.ai/settings/nautex-api",
                              url="(https://app.nautex.ai/settings/nautex-api)", tooltip="Get API Key")

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

        # Create loadable list widgets
        self.projects_list = LoadableList(
            title="Projects",
            data_loader=self.projects_loader,
            on_change=self.on_project_selection_change,
        )

        # For List 2 we provide the loader that references the first list's selection
        self.impl_plans_list = LoadableList(
            title="Implementation plans",
            data_loader=self.implementation_plans_loader,
            on_change=self.on_impl_plan_selection_change,
        )
        self.impl_plans_list.set_empty_message("Select a project to view implementation plans.")

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
            self.projects_list,
            self.impl_plans_list,
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
            acc_info = await self.api_service.get_account_info(token_override=value, raise_exception=True, timeout=5.0)
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
        tkm = self.config_service.config.api_token.get_secret_value()
        self.config_service.save_token_to_nautex_env(tkm)
        self.config_service.save_configuration()

        # Refresh the projects list when token is set
        if token:
            self.projects_list.reload()

    async def set_agent_name(self, name: str) -> None:
        self.config_service.config.agent_instance_name = name
        self.config_service.save_configuration()

        # ------------------------------------------------------------------
        # Data loaders for projects and implementation plans
        # ------------------------------------------------------------------

    async def projects_loader(self) -> Tuple[list, Optional[int]]:
        """Load projects from the API.

        Returns:
            A tuple of (projects_list, selected_index) where selected_index
            is the index of the project to be selected after loading (if any).
        """
        try:
            # Get projects from the API
            projects_resp = await self.api_service.list_projects()
            selected_index = None

            projects = [ProjectItem(id=pr.project_id, name=pr.name) for pr in projects_resp]

            # If we have a project_id in config, find its index to mark it as selected
            if self.config_service.config.project_id:
                for i, project in enumerate(projects):
                    if project.id == self.config_service.config.project_id:
                        selected_index = i
                        break

            return projects, selected_index
        except Exception as e:
            self.app.log(f"Error loading projects: {str(e)}")
            self.projects_list.set_empty_message("No projects available. Ensure API connectivity")
            return [], None

    async def implementation_plans_loader(self) -> Tuple[list, Optional[int]]:
        """Load implementation plans for the selected project.

        Returns:
            A tuple of (plans_list, selected_index) where selected_index
            is the index of the plan to be selected after loading (if any).
        """
        try:
            # Check if we have a valid token and selected project
            token = self.config_service.config.api_token.get_secret_value() if self.config_service.config.api_token else None
            if not token:
                self.impl_plans_list.set_empty_message("No API token provided")
                return [], None

            selected_project = self.projects_list.selected_item
            if not selected_project:
                self.impl_plans_list.set_empty_message("Select a project to view implementation plans")
                return [], None

            # Get implementation plans from the API
            plans_resp = await self.api_service.list_implementation_plans(selected_project.id)
            plans = [ImplementationPlanItem(id=p.plan_id, name=p.name) for p in plans_resp]
            selected_index = None

            if self.config_service.config.plan_id:
                for i, plan in enumerate(plans):
                    if plan.id == self.config_service.config.plan_id:
                        selected_index = i
                        break

            # If no plans were found but no error occurred, show a message to create one
            if not plans:
                self.impl_plans_list.set_empty_message("No implementation plans found.\nCreate one in the Nautex app.\nGo to app.nautex.ai")

            return plans, selected_index

        except Exception as e:
            self.app.log(f"Error loading implementation plans: {str(e)}")
            self.impl_plans_list.set_empty_message(f"Error loading plans: {str(e)}")
            return [], None


    async def on_project_selection_change(self, selected_item: ProjectItem) -> None:
        """Handle selection change in the first list."""
        self.app.log(f"Project selection changed: {selected_item.name if hasattr(selected_item, 'name') else selected_item}")

        self.config_service.config.project_id = selected_item.id
        self.config_service.save_configuration()

        # Refresh the implementation plans list
        self.impl_plans_list.reload()


    async def on_impl_plan_selection_change(self, selected_item: ImplementationPlanItem) -> None:
        """Handle selection change in the implementation plans list."""
        self.app.log(f"Implementation plan selection changed: {selected_item.name if hasattr(selected_item, 'name') else selected_item}")

        self.config_service.config.plan_id = selected_item.id

        # touching the plan for pushing notification for an onboarding process
        plan = await self.api_service.get_implementation_plan(self.config_service.config.project_id,
                                                              self.config_service.config.plan_id)
        self.config_service.save_configuration()


    def compose(self) -> ComposeResult:
        # Header with centered title
        yield Static("Nautex MCP server: Setup", id="header")

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
                yield self.projects_list
                yield self.impl_plans_list

        # Environment info with CWD before footer
        yield Static(f"Current Working Directory: {path2display(self.config_service.cwd)}", id="environment_info")
        yield Footer()

    async def update_integration_status(self):
        status = await self.integration_status_service.get_integration_status()
        self._on_integration_status_update(status)


    async def on_mount(self) -> None:
        # Get initial integration status
        await self.update_integration_status()

        await self._update_system_info()
        self.api_token_input.focus()

        # Start polling for integration status updates
        self.integration_status_service.start_polling(on_update=self._on_integration_status_update)

        # Load projects on start
        self.projects_list.reload()

    async def on_unmount(self) -> None:
        """Called when the screen is unmounted."""
        # Stop polling when screen is unmounted
        self.integration_status_service.stop_polling()

    def _on_integration_status_update(self, status: IntegrationStatus) -> None:
        """Callback function for integration status updates.

        Args:
            status: The updated integration status
        """
        self.integration_status_widget.update_data(status)
        self.system_info_widget.update_system_info(
            email=status.account_info.profile_email if status.account_info else None,
            network_delay=status.network_response_time
        )

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

    def show_dialog(self, dialog):
        self._run_dialog_worker(dialog)

    @work
    async def _run_dialog_worker(self, dialog):
        await self.app.push_screen_wait(dialog)
        await self._update_system_info()
        await self.update_integration_status()

    async def action_show_mcp_dialog(self) -> None:
        dialog = MCPConfigWriteDialog(mcp_service=self.mcp_config_service)
        self.show_dialog(dialog)


    async def action_show_agent_rules_dialog(self) -> None:
        dialog = AgentRulesWriteDialog(rules_service=self.agent_rules_service)
        self.show_dialog(dialog)

    async def action_show_agent_selection_dialog(self) -> None:
        dialog = AgentSelectionDialog(
            config_service=self.config_service,
            integration_status_service=self.integration_status_service
        )

        self.show_dialog(dialog)

    async def action_show_info_help(self) -> None:
        """Show the info and help dialog."""
        dialog = InfoHelpDialog()
        self.show_dialog(dialog)


    async def _update_system_info(self) -> None:
        """Update the system info widget with current data."""
        # Get agent_type from config
        agent_type = self.config_service.config.agent_type

        mcp_config_status, _ = await self.mcp_config_service.check_mcp_configuration()
        agent_rules_status, _ = self.agent_rules_service.validate_rules()

        self.system_info_widget.update_system_info(
            host=self.config_service.config.api_host,
            agent_type=agent_type,
            mcp_config_status=mcp_config_status,
            agent_rules_status=agent_rules_status
        )

    async def on_toggle_button_click(self) -> None:
        """Enable or disable List 1 based on its current state."""
        if self.projects_list.is_disabled:
            self.projects_list.enable()
            self.toggle_button.label = "Disable List 1"
        else:
            self.projects_list.disable()
            self.toggle_button.label = "Enable List 1"

        # Reload List 1 so the UI updates accordingly (shows disabled msg if needed)
        self.projects_list.reload()



    async def on_reload_button_click(self) -> None:
        """Reload both lists."""
        self.app.log("Reloading lists...")
        self.projects_list.reload()
        self.impl_plans_list.reload()


class SetupApp(App):
    """TUI application for the setup command."""

    def __init__(self,
                 config_service: ConfigurationService,
                 api_service: NautexAPIService,
                 integration_status_service: IntegrationStatusService,
                 mcp_config_service: MCPConfigService = None,
                 agent_rules_service: AgentRulesService = None,
                 **kwargs):
        super().__init__(**kwargs)
        self.config_service = config_service
        self.api_service = api_service
        self.integration_status_service = integration_status_service
        self.mcp_config_service = mcp_config_service
        self.agent_rules_service = agent_rules_service

    def on_mount(self) -> None:
        """Called when the app starts."""
        setup_screen = SetupScreen(
            config_service=self.config_service,
            integration_status_service=self.integration_status_service,
            api_service=self.api_service,
            mcp_config_service=self.mcp_config_service,
            agent_rules_service=self.agent_rules_service,
        )
        self.push_screen(setup_screen)

    async def on_shutdown(self) -> None:
        """Called when the app is shutting down."""
        # Stop polling and close API client to prevent "Unclosed client session" errors
        self.integration_status_service.stop_polling()
        await self.api_service.api_client.close()
