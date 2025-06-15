"""TUI screen for the interactive setup process."""

from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Header, Footer

from ..widgets import (
    AccountStatusPanel,
    ApiTokenInput,
    CompactInput,
    CompactHorizontalLayout,
    ConfigurationSummaryView,
    ConfirmationDialog,
    IntegrationStatusWidget,
    TitledOptionList,
)
from ...services.config_service import ConfigurationService, ConfigurationError
from ...services.integration_status_service import IntegrationStatusService
from ...services.mcp_config_service import MCPConfigService
from ...services.nautex_api_service import NautexAPIService
from ...models.config_models import NautexConfig
from ...models.api_models import Project, ImplementationPlan


class SetupScreen(Screen):
    """Interactive setup screen for configuring the Nautex CLI."""

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
        Binding("ctrl+s", "save_config", "Save & Exit"),
        Binding("enter", "handle_enter", "Next", show=True),
        Binding("f1", "show_help", "Help"),
    ]

    CSS = """
    #status_section {
        height: auto;
        margin: 0;
        padding: 0;
    }
    
    #main_content {
        padding: 1;
        margin: 0;
    }
    #button_section {
        height: 1;
        dock: bottom;
        margin: 0;
        padding: 0;
    }
    """

    def __init__(
        self,
        config_service: ConfigurationService,
        project_root: Path,
        integration_status_service: IntegrationStatusService,
        api_service: NautexAPIService = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.config_service = config_service
        self.project_root = project_root
        self.integration_status_service = integration_status_service
        self.api_service = api_service

        # Setup state
        self.current_step = "token"
        self.setup_data = {}
        self.projects_list = []
        self.plans_list = []
        self.account_info = None

        # Widget references
        self.integration_status_widget = IntegrationStatusWidget()
        self.api_token_input = ApiTokenInput()
        self.agent_name_input = CompactInput("Agent Instance Name", "e.g., my-dev-agent")
        self.account_panel = AccountStatusPanel()
        self.projects_list_widget = TitledOptionList("Select Project")
        self.plans_list_widget = TitledOptionList("Select Implementation Plan")
        self.config_summary = ConfigurationSummaryView()
        self.next_button = Button("Next", id="next_button", variant="primary")
        self.back_button = Button("Back", id="back_button", variant="default")
        self.save_button = Button("Save Configuration", id="save_button", variant="success")

        self._load_existing_config()

    def compose(self) -> ComposeResult:
        # yield Header()
        with Vertical(id="status_section"):
            yield self.integration_status_widget
        with Vertical(id="main_content"):
            with CompactHorizontalLayout(id="input_info_layout"):
                with Vertical(id="input_section"):
                    yield self.api_token_input
                    yield self.agent_name_input
                with Vertical(id="info_section"):
                    yield self.account_panel
            with Horizontal(id="selection_section"):
                yield self.projects_list_widget
                yield self.plans_list_widget
            yield self.config_summary
        with Horizontal(id="button_section"):
            yield self.back_button
            yield self.next_button
            yield self.save_button
        yield Footer()

    async def on_mount(self) -> None:
        await self._update_integration_status()
        await self._update_display()
        if self.current_step == "token":
            self.api_token_input.focus()
        elif self.current_step == "agent_name":
            self.agent_name_input.focus()

    def _load_existing_config(self) -> None:
        try:
            if self.config_service.config_exists():
                config = self.config_service.load_configuration()
                if hasattr(config, "api_token") and config.api_token:
                    self.setup_data["api_token"] = config.api_token.get_secret_value()
                if hasattr(config, "agent_instance_name") and config.agent_instance_name:
                    self.setup_data["agent_instance_name"] = config.agent_instance_name
                if hasattr(config, "project_id") and config.project_id:
                    self.setup_data["project_id"] = config.project_id
                if hasattr(config, "implementation_plan_id") and config.implementation_plan_id:
                    self.setup_data["implementation_plan_id"] = config.implementation_plan_id
                # Account info is now retrieved directly from the API when needed
        except ConfigurationError:
            pass

    async def _update_display(self) -> None:
        self.api_token_input.display = False
        self.agent_name_input.display = False
        self.account_panel.display = False
        self.projects_list_widget.display = False
        self.plans_list_widget.display = False
        self.config_summary.display = False
        self.back_button.display = False
        self.next_button.display = False
        self.save_button.display = False

        await self._update_integration_status()

        if self.current_step == "token":
            self.api_token_input.display = True
            if self.setup_data.get("api_token"):
                self.api_token_input.set_value(self.setup_data["api_token"])
            self.next_button.display = True
            self.next_button.label = "Next"
            self.api_token_input.focus()
        elif self.current_step == "agent_name":
            self.api_token_input.display = True
            self.agent_name_input.display = True
            if self.setup_data.get("agent_instance_name"):
                self.agent_name_input.set_value(self.setup_data["agent_instance_name"])
            self.back_button.display = True
            self.next_button.display = True
            self.next_button.label = "Validate"
            self.agent_name_input.focus()
        elif self.current_step == "validate":
            self.api_token_input.display = True
            self.agent_name_input.display = True
            self.account_panel.display = True
            self.back_button.display = True
            self.next_button.display = True
            self.next_button.label = "Continue"
        elif self.current_step == "projects":
            self.account_panel.display = True
            self.projects_list_widget.display = True
            self.back_button.display = True
            self.next_button.display = True
            self.next_button.label = "Select Project"
        elif self.current_step == "plans":
            self.account_panel.display = True
            self.projects_list_widget.display = True
            self.plans_list_widget.display = True
            self.back_button.display = True
            self.next_button.display = True
            self.next_button.label = "Select Plan"
        elif self.current_step == "summary":
            self.config_summary.display = True
            self.back_button.display = True
            self.save_button.display = True

    async def action_handle_enter(self) -> None:
        if self.next_button.display:
            await self._handle_next()
        elif self.save_button.display:
            await self._handle_save()

    async def action_show_help(self) -> None:
        help_text = """
🔧 Nautex Setup Help
Steps:
1. API Token: Get your token from app.nautex.ai/new_token
2. Agent Name: Choose a name for this agent instance
3. Validation: We'll verify your API connection
4. Project: Select which project to work on
5. Plan: Choose an implementation plan
6. Summary: Review and save your configuration
Navigation:
• Enter: Go to next step
• Tab: Navigate between fields
• Ctrl+S: Save and exit
• Esc: Cancel setup
        """
        await self._show_info("Setup Help", help_text.strip())

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "next_button":
            await self._handle_next()
        elif event.button.id == "back_button":
            await self._handle_back()
        elif event.button.id == "save_button":
            await self._handle_save()

    async def _handle_next(self) -> None:
        if self.current_step == "token":
            token_value = self.api_token_input.value.strip()
            if not token_value:
                await self._show_error("Please enter an API token")
                return
            self.setup_data["api_token"] = token_value
            self.current_step = "agent_name"
            await self._update_display()
        elif self.current_step == "agent_name":
            agent_name = self.agent_name_input.value.strip()
            if not agent_name:
                await self._show_error("Please enter an agent instance name")
                return
            self.setup_data["agent_instance_name"] = agent_name
            await self._validate_api()
        elif self.current_step == "validate":
            self.current_step = "projects"
            await self._load_projects()
        elif self.current_step == "projects":
            selected_project = self._get_selected_project()
            if not selected_project:
                await self._show_error("Please select a project")
                return
            self.setup_data["project_id"] = selected_project.id
            self.setup_data["project_name"] = selected_project.name
            self.current_step = "plans"
            await self._load_plans(selected_project.id)
        elif self.current_step == "plans":
            selected_plan = self._get_selected_plan()
            if not selected_plan:
                await self._show_error("Please select an implementation plan")
                return
            self.setup_data["implementation_plan_id"] = selected_plan.id
            self.setup_data["plan_name"] = selected_plan.name
            self.current_step = "summary"
            await self._show_summary()
            await self._update_display()

    async def _handle_back(self) -> None:
        step_map = {
            "agent_name": "token",
            "validate": "agent_name",
            "projects": "validate",
            "plans": "projects",
            "summary": "plans",
        }
        self.current_step = step_map.get(self.current_step, "token")
        await self._update_display()

    async def _handle_save(self) -> None:
        try:
            config_data = {
                "api_token": self.setup_data["api_token"],
                "agent_instance_name": self.setup_data["agent_instance_name"],
                "project_id": self.setup_data["project_id"],
                "implementation_plan_id": self.setup_data["implementation_plan_id"],
                # account_details is no longer stored in config
            }
            config = NautexConfig(**config_data)
            self.config_service.save_configuration(config)
            self.integration_status_widget.update_status("mcp", "🟢")
            await self._show_confirmation("Configuration saved successfully!")
            self.app.exit()
        except Exception as e:
            await self._show_error(f"Failed to save configuration: {e}")

    async def _validate_api(self) -> None:
        try:
            self.integration_status_widget.update_status("network", "🟡")
            is_valid, account_info, error_msg = await self.integration_status_service.validate_api_token(
                self.setup_data["api_token"]
            )
            if is_valid and account_info:
                self.account_info = account_info

                # Get API service to access latency information
                api_service = self._get_api_service()
                # Use overall API latency
                _, max_latency = api_service.api_latency

                self.account_panel.show_account_info(
                    self.account_info.profile_email,
                    self.account_info.api_version,
                    max_latency,  # Use max latency from the API service
                )
                self.integration_status_widget.update_status("network", "🟢")
                self.integration_status_widget.update_status("api", "🟢")
                self.current_step = "validate"
            else:
                self.integration_status_widget.update_status("network", "🔴")
                self.integration_status_widget.update_status("api", "🔴")
                await self._show_error(f"API validation failed: {error_msg}")
        except Exception as e:
            self.integration_status_widget.update_status("network", "🔴")
            await self._show_error(f"Network error: {e}")
        finally:
            await self._update_display()

    def _get_api_service(self):
        if self.api_service:
            return self.api_service
        from ...api import create_api_client
        import os
        test_mode = os.getenv('NAUTEX_API_TEST_MODE', 'true').lower() == 'true'
        api_client = create_api_client(base_url="https://api.nautex.ai", test_mode=test_mode)
        temp_config = NautexConfig(
            api_token=self.setup_data['api_token'],
            agent_instance_name=self.setup_data['agent_instance_name']
        )
        self.api_service = NautexAPIService(api_client, temp_config)
        return self.api_service

    async def _load_projects(self) -> None:
        try:
            self.projects_list_widget.set_loading(True)
            await self._update_display()
            api_service = self._get_api_service()
            self.projects_list = await api_service.list_projects()
            project_options = [f"{p.name} ({p.id})" for p in self.projects_list]
            self.projects_list_widget.set_options(project_options)
            self.integration_status_widget.update_status("project", "🟡")
        except Exception as e:
            await self._show_error(f"Failed to load projects: {e}")
        finally:
            await self._update_display()

    async def _load_plans(self, project_id: str) -> None:
        try:
            self.plans_list_widget.set_loading(True)
            await self._update_display()
            api_service = self._get_api_service()
            self.plans_list = await api_service.list_implementation_plans(project_id)
            plan_options = [f"{p.name} ({p.id})" for p in self.plans_list]
            self.plans_list_widget.set_options(plan_options)
            self.integration_status_widget.update_status("plan", "🟡")
        except Exception as e:
            await self._show_error(f"Failed to load implementation plans: {e}")
        finally:
            await self._update_display()

    def _get_selected_project(self) -> Optional[Project]:
        highlighted = self.projects_list_widget.option_list.highlighted
        if highlighted is not None and highlighted < len(self.projects_list):
            return self.projects_list[highlighted]
        return None

    def _get_selected_plan(self) -> Optional[ImplementationPlan]:
        highlighted = self.plans_list_widget.option_list.highlighted
        if highlighted is not None and highlighted < len(self.plans_list):
            return self.plans_list[highlighted]
        return None

    async def _show_summary(self) -> None:
        summary_data = {
            "API Token": "*" * 8 + "...",
            "Agent Name": self.setup_data.get("agent_instance_name", ""),
            "Email": self.account_info.profile_email if self.account_info else "",
            "Project": self.setup_data.get("project_name", ""),
            "Implementation Plan": self.setup_data.get("plan_name", ""),
        }
        self.config_summary.show_config(summary_data)
        self.integration_status_widget.update_status("project", "🟢")
        self.integration_status_widget.update_status("plan", "🟢")
        await self._update_display()

    async def _show_error(self, message: str) -> None:
        await self.app.push_screen(ConfirmationDialog(message=message, title="Error"))

    async def _show_info(self, title: str, message: str) -> None:
        await self.app.push_screen(ConfirmationDialog(message=message, title=title))

    async def _show_confirmation(self, message: str) -> None:
        await self.app.push_screen(ConfirmationDialog(message=message, title="Success"))

    def action_quit(self) -> None:
        self.app.exit()

    async def action_save_config(self) -> None:
        if self.current_step == "summary":
            await self._handle_save()

    async def _update_integration_status(self) -> None:
        try:
            status = await self.integration_status_service.get_integration_status()
            self.integration_status_widget.update_from_integration_status(status)
        except Exception:
            pass


class SetupApp(App):
    """TUI application for the setup command."""

    def __init__(self, config_service: ConfigurationService, project_root: Path, **kwargs):
        super().__init__(**kwargs)
        self.config_service = config_service
        self.project_root = project_root

    def on_mount(self) -> None:
        """Called when the app starts."""
        mcp_config_service = MCPConfigService()
        integration_status_service = IntegrationStatusService(
            config_service=self.config_service,
            mcp_config_service=mcp_config_service,
            project_root=self.project_root,
        )
        setup_screen = SetupScreen(
            config_service=self.config_service,
            project_root=self.project_root,
            integration_status_service=integration_status_service,
        )
        self.push_screen(setup_screen)
