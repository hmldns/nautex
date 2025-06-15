"""TUI screens for the Nautex CLI application."""

import asyncio
from typing import Optional, List, Dict, Any
from pathlib import Path

from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Button, Static, Label, Input
from textual.containers import Horizontal, Vertical, Center, Middle
from textual.binding import Binding
from textual import events

from .widgets import (
    SetupStatusPanel, 
    ConfigurationSummaryView, 
    TitledInput, 
    TitledOptionList, 
    AccountStatusPanel, 
    ConfirmationDialog,
    CompactInput,
    ApiTokenInput,
    IntegrationStatusWidget,
    StepByStepLayout,
    CompactHorizontalLayout,
    PlanContextWidget,
    get_shared_integration_status_widget
)
from ..services.config_service import ConfigurationService, ConfigurationError
from ..services.integration_status_service import IntegrationStatusService
from ..services.mcp_config_service import MCPConfigService
from ..services.nautex_api_service import NautexAPIService
from ..api.client import NautexAPIError
from ..models.config_models import NautexConfig, AccountInfo
from ..models.api_models import Project, ImplementationPlan


class SetupScreen(Screen):
    """Interactive setup screen for configuring the Nautex CLI."""
    
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
        Binding("ctrl+s", "save_config", "Save & Exit"),
        Binding("enter", "handle_enter", "Next", show=True),
        Binding("f1", "show_help", "Help"),
    ]
    
    DEFAULT_CSS = """
    SetupScreen {
        layout: vertical;
        background: $background;
    }
    
    #status_section {
        height: 8;
        dock: top;
        background: $panel;
        border: solid $primary;
        margin: 1;
        padding: 1;
    }
    
    #main_content {
        height: auto;
    }
    
    #input_section {
        height: auto;
        margin: 1;
    }
    
    #info_section {
        width: 1fr;
        height: auto;
        margin: 1;
    }
    
    #selection_section {
        height: auto;
        margin: 1;
    }
    
    #button_section {
        height: 3;
        dock: bottom;
        background: $panel;
        margin: 1;
    }
    
    .widget_title {
        text-style: bold;
        color: $primary;
    }
    """
    
    def __init__(self, config_service: ConfigurationService, project_root: Path, **kwargs):
        super().__init__(**kwargs)
        self.config_service = config_service
        self.project_root = project_root
        
        # Setup state
        self.current_step = "token"  # token -> agent_name -> validate -> projects -> plans -> summary -> save
        self.setup_data = {}
        self.projects_list = []
        self.plans_list = []
        self.account_info = None
        self.api_service = None
        
        # Create integration status service for real-time status updates
        from ..services.mcp_config_service import MCPConfigService
        mcp_config_service = MCPConfigService()
        self.integration_status_service = IntegrationStatusService(
            config_service=self.config_service,
            mcp_config_service=mcp_config_service,
            project_root=self.project_root
        )
        
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
        
        # Load existing config if available
        self._load_existing_config()
    
    def compose(self) -> ComposeResult:
        """Compose the setup screen layout."""
        # Status section (always visible at top)
        with Vertical(id="status_section"):
            yield self.integration_status_widget
        
        with Vertical(id="main_content"):
            # Input and info section (side by side)
            with CompactHorizontalLayout(id="input_info_layout"):
                # Left side: Input fields
                with Vertical(id="input_section"):
                    yield self.api_token_input
                    yield self.agent_name_input
                
                # Right side: Info widget
                with Vertical(id="info_section"):
                    yield self.account_panel
                    
            # Selection section (full width)
            with Horizontal(id="selection_section"):
                yield self.projects_list_widget
                yield self.plans_list_widget
                
            # Summary section
            yield self.config_summary
            
        # Button section (always visible at bottom)
        with Horizontal(id="button_section"):
            yield self.back_button
            yield self.next_button
            yield self.save_button
    
    async def on_mount(self) -> None:
        """Called when the screen is mounted."""
        await self._update_integration_status()
        await self._update_display()
        # Focus the appropriate input field
        if self.current_step == "token":
            self.api_token_input.focus()
        elif self.current_step == "agent_name":
            self.agent_name_input.focus()
    
    def _load_existing_config(self) -> None:
        """Load existing configuration to pre-fill fields."""
        try:
            if self.config_service.config_exists():
                config = self.config_service.load_configuration()
                
                # Pre-fill token and agent name
                if hasattr(config, 'api_token') and config.api_token:
                    self.setup_data['api_token'] = config.api_token.get_secret_value()
                
                if hasattr(config, 'agent_instance_name') and config.agent_instance_name:
                    self.setup_data['agent_instance_name'] = config.agent_instance_name
                
                if hasattr(config, 'project_id') and config.project_id:
                    self.setup_data['project_id'] = config.project_id
                
                if hasattr(config, 'implementation_plan_id') and config.implementation_plan_id:
                    self.setup_data['implementation_plan_id'] = config.implementation_plan_id
                
                if hasattr(config, 'account_details') and config.account_details:
                    self.account_info = config.account_details
                    
        except ConfigurationError:
            # No existing config or invalid config - start fresh
            pass
    
    async def _update_display(self) -> None:
        """Update the display based on current step."""
        # Hide all sections initially
        self.api_token_input.display = False
        self.agent_name_input.display = False
        self.account_panel.display = False
        self.projects_list_widget.display = False
        self.plans_list_widget.display = False
        self.config_summary.display = False
        self.back_button.display = False
        self.next_button.display = False
        self.save_button.display = False
        
        # Update status panel - handled by integration status service
        await self._update_integration_status()
        
        # Show relevant sections based on current step
        if self.current_step == "token":
            self.api_token_input.display = True
            if self.setup_data.get('api_token'):
                self.api_token_input.set_value(self.setup_data['api_token'])
            self.next_button.display = True
            self.next_button.label = "Next"
            self.api_token_input.focus()
            
        elif self.current_step == "agent_name":
            self.api_token_input.display = True
            self.agent_name_input.display = True
            if self.setup_data.get('agent_instance_name'):
                self.agent_name_input.set_value(self.setup_data['agent_instance_name'])
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
        """Handle Enter key press - same as next button."""
        if self.next_button.display:
            await self._handle_next()
        elif self.save_button.display:
            await self._handle_save()
    
    async def action_show_help(self) -> None:
        """Show help information."""
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
        """Handle button press events."""
        if event.button.id == "next_button":
            await self._handle_next()
        elif event.button.id == "back_button":
            await self._handle_back()
        elif event.button.id == "save_button":
            await self._handle_save()
    
    async def _handle_next(self) -> None:
        """Handle next button press based on current step."""
        if self.current_step == "token":
            # Collect token and move to agent name
            token_value = self.api_token_input.value.strip()
            if not token_value:
                await self._show_error("Please enter an API token")
                return
            
            self.setup_data['api_token'] = token_value
            self.current_step = "agent_name"
            await self._update_display()
            
        elif self.current_step == "agent_name":
            # Collect agent name and validate API
            agent_name = self.agent_name_input.value.strip()
            if not agent_name:
                await self._show_error("Please enter an agent instance name")
                return
            
            self.setup_data['agent_instance_name'] = agent_name
            await self._validate_api()
            
        elif self.current_step == "validate":
            # Move to projects selection
            self.current_step = "projects"
            await self._load_projects()
            
        elif self.current_step == "projects":
            # Get selected project and move to plans
            selected_project = self._get_selected_project()
            if not selected_project:
                await self._show_error("Please select a project")
                return
            
            self.setup_data['project_id'] = selected_project.id
            self.setup_data['project_name'] = selected_project.name
            
            self.current_step = "plans"
            await self._load_plans(selected_project.id)
            
        elif self.current_step == "plans":
            # Get selected plan and show summary
            selected_plan = self._get_selected_plan()
            if not selected_plan:
                await self._show_error("Please select an implementation plan")
                return
            
            self.setup_data['implementation_plan_id'] = selected_plan.id
            self.setup_data['plan_name'] = selected_plan.name
            
            self.current_step = "summary"
            await self._show_summary()
            await self._update_display()
    
    async def _handle_back(self) -> None:
        """Handle back button press."""
        if self.current_step == "agent_name":
            self.current_step = "token"
        elif self.current_step == "validate":
            self.current_step = "agent_name"
        elif self.current_step == "projects":
            self.current_step = "validate"
        elif self.current_step == "plans":
            self.current_step = "projects"
        elif self.current_step == "summary":
            self.current_step = "plans"
        
        await self._update_display()
    
    async def _handle_save(self) -> None:
        """Handle save configuration."""
        try:
            # Create config from setup data
            config_data = {
                'api_token': self.setup_data['api_token'],
                'agent_instance_name': self.setup_data['agent_instance_name'],
                'project_id': self.setup_data['project_id'],
                'implementation_plan_id': self.setup_data['implementation_plan_id'],
                'account_details': self.account_info.model_dump() if self.account_info else None
            }
            
            # Create and save the config
            config = NautexConfig(**config_data)
            self.config_service.save_configuration(config)
            
            # Update status
            self.integration_status_widget.update_status("mcp", "🟢")
            
            # Show success message and exit
            await self._show_confirmation("Configuration saved successfully!")
            self.app.exit()
            
        except Exception as e:
            await self._show_error(f"Failed to save configuration: {e}")
    
    async def _validate_api(self) -> None:
        """Validate API token and get account info."""
        try:
            self.integration_status_widget.update_status("network", "🟡")
            
            # Use IntegrationStatusService for API validation
            mcp_config_service = MCPConfigService()
            integration_service = IntegrationStatusService(
                config_service=self.config_service,
                mcp_config_service=mcp_config_service
            )
            
            # Validate token using the integration service
            is_valid, account_info, error_msg = await integration_service.validate_api_token(
                self.setup_data['api_token']
            )
            
            if is_valid and account_info:
                self.account_info = account_info
                
                # Update UI with account info
                self.account_panel.show_account_info(
                    self.account_info.profile_email,
                    self.account_info.api_version,
                    self.account_info.response_latency
                )
                
                self.integration_status_widget.update_status("network", "🟢")
                self.integration_status_widget.update_status("api", "🟢")
                
                self.current_step = "validate"
                await self._update_display()
            else:
                self.integration_status_widget.update_status("network", "🔴")
                self.integration_status_widget.update_status("api", "🔴")
                await self._show_error(f"API validation failed: {error_msg}")
            
        except Exception as e:
            self.integration_status_widget.update_status("network", "🔴")
            await self._show_error(f"Network error: {e}")
    
    async def _load_projects(self) -> None:
        """Load available projects."""
        try:
            self.projects_list_widget.set_loading(True)
            
            # Create a minimal config for API service
            temp_config = NautexConfig(
                api_token=self.setup_data['api_token'],
                agent_instance_name=self.setup_data['agent_instance_name']
            )
            
            from ..api import create_api_client
            import os
            
            # Check for test mode from environment or config default
            test_mode = os.getenv('NAUTEX_API_TEST_MODE', 'true').lower() == 'true'
            api_client = create_api_client(base_url="https://api.nautex.ai", test_mode=test_mode)
            self.api_service = NautexAPIService(api_client, temp_config)
            
            self.projects_list = await self.api_service.list_projects()
            
            # Update widget with project options
            project_options = [f"{p.name} ({p.id})" for p in self.projects_list]
            self.projects_list_widget.set_options(project_options)
            
            self.integration_status_widget.update_status("project", "🟡")
            await self._update_display()
            
        except Exception as e:
            await self._show_error(f"Failed to load projects: {e}")
    
    async def _load_plans(self, project_id: str) -> None:
        """Load implementation plans for selected project."""
        try:
            self.plans_list_widget.set_loading(True)
            
            self.plans_list = await self.api_service.list_implementation_plans(project_id)
            
            # Update widget with plan options
            plan_options = [f"{p.name} ({p.id})" for p in self.plans_list]
            self.plans_list_widget.set_options(plan_options)
            
            self.integration_status_widget.update_status("plan", "🟡")
            await self._update_display()
            
        except Exception as e:
            await self._show_error(f"Failed to load implementation plans: {e}")
    
    def _get_selected_project(self) -> Optional[Project]:
        """Get the currently selected project."""
        if not hasattr(self.projects_list_widget.option_list, 'highlighted'):
            return None
        
        highlighted_index = self.projects_list_widget.option_list.highlighted
        if highlighted_index is not None and highlighted_index < len(self.projects_list):
            return self.projects_list[highlighted_index]
        return None
    
    def _get_selected_plan(self) -> Optional[ImplementationPlan]:
        """Get the currently selected plan."""
        if not hasattr(self.plans_list_widget.option_list, 'highlighted'):
            return None
        
        highlighted_index = self.plans_list_widget.option_list.highlighted
        if highlighted_index is not None and highlighted_index < len(self.plans_list):
            return self.plans_list[highlighted_index]
        return None
    
    async def _show_summary(self) -> None:
        """Show configuration summary."""
        summary_data = {
            'API Token': '*' * 8 + '...',
            'Agent Name': self.setup_data.get('agent_instance_name', ''),
            'Email': self.account_info.profile_email if self.account_info else '',
            'Project': self.setup_data.get('project_name', ''),
            'Implementation Plan': self.setup_data.get('plan_name', ''),
        }
        
        self.config_summary.show_config(summary_data)
        self.integration_status_widget.update_status("project", "🟢")
        self.integration_status_widget.update_status("plan", "🟢")
        await self._update_display()
    
    async def _show_error(self, message: str) -> None:
        """Show error dialog."""
        def handle_result(result: bool) -> None:
            pass  # Just dismiss the dialog
        
        error_dialog = ConfirmationDialog(
            message=message,
            title="Error"
        )
        self.app.push_screen(error_dialog, handle_result)
    
    async def _show_info(self, title: str, message: str) -> None:
        """Show info dialog."""
        def handle_result(result: bool) -> None:
            pass  # Just dismiss the dialog
        
        info_dialog = ConfirmationDialog(
            message=message,
            title=title
        )
        self.app.push_screen(info_dialog, handle_result)
    
    async def _show_confirmation(self, message: str) -> None:
        """Show confirmation dialog."""
        def handle_result(result: bool) -> None:
            pass  # Just dismiss the dialog
        
        confirm_dialog = ConfirmationDialog(
            message=message,
            title="Success"
        )
        self.app.push_screen(confirm_dialog, handle_result)
    
    def action_quit(self) -> None:
        """Quit the application."""
        self.app.exit()
    
    async def action_save_config(self) -> None:
        """Save configuration shortcut."""
        if self.current_step == "summary":
            await self._handle_save()
    
    async def _update_integration_status(self) -> None:
        """Update the integration status widget with current status."""
        try:
            integration_status = await self.integration_status_service.get_integration_status()
            self.integration_status_widget.update_from_integration_status(integration_status)
        except Exception as e:
            # If we can't get status, show a basic message
            pass


class StatusScreen(App):
    """TUI application for displaying current status and configuration."""
    
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
    ]
    
    def __init__(self, plan_context, integration_status_service=None, **kwargs):
        super().__init__(**kwargs)
        self.plan_context = plan_context
        self.integration_status_service = integration_status_service
        
        # Use shared integration status widget
        self.integration_status_widget = get_shared_integration_status_widget()
        
        # Create plan context widget
        self.plan_context_widget = PlanContextWidget()
    
    def compose(self) -> ComposeResult:
        """Compose the status screen layout."""
        yield Static("🚀 Nautex CLI Status", id="title")
        
        with Vertical(id="main_content"):
            # Integration Status (using the same widget as setup)
            yield self.integration_status_widget
            
            # Plan Context Information  
            yield self.plan_context_widget
            
            # Configuration Details
            yield Static("📋 Configuration Details", classes="section_header")
            if self.plan_context.config_summary:
                config = self.plan_context.config_summary
                yield Static(f"   Agent Name: {config.get('agent_instance_name', 'Not set')}")
                yield Static(f"   Project ID: {config.get('project_id', 'Not set')}")
                yield Static(f"   Plan ID: {config.get('implementation_plan_id', 'Not set')}")
                yield Static(f"   API Token: {'✅ Configured' if config.get('has_token') else '❌ Missing'}")
            else:
                yield Static("   ❌ No configuration found")
            
            yield Static("")  # Spacer
            
            # MCP Status
            yield Static("🔌 MCP Integration", classes="section_header")
            mcp_status_emoji = {
                "OK": "✅",
                "NOT_FOUND": "❌", 
                "INVALID": "⚠️",
                "ERROR": "❌"
            }
            emoji = mcp_status_emoji.get(self.plan_context.mcp_status.value, "❓")
            yield Static(f"   {emoji} Status: {self.plan_context.mcp_status.value}")
            if self.plan_context.mcp_config_path:
                yield Static(f"   📁 Config: {self.plan_context.mcp_config_path}")
            
            yield Static("")  # Spacer
            
            # Next Task
            yield Static("📋 Next Task", classes="section_header")
            if self.plan_context.next_task:
                task = self.plan_context.next_task
                yield Static(f"   🎯 {task.task_designator}: {task.name}")
                yield Static(f"   📝 {task.description}")
                yield Static(f"   📊 Status: {task.status}")
            else:
                yield Static("   ℹ️ No tasks available")
            
            yield Static("")  # Spacer
            
            # Advised Action
            yield Static("💡 Recommended Action", classes="section_header")
            yield Static(f"   {self.plan_context.advised_action}")
    
    async def on_mount(self) -> None:
        """Called when the screen is mounted."""
        # Update the integration status widget
        if self.integration_status_service:
            # Use the actual integration status service for real-time status
            try:
                integration_status = await self.integration_status_service.get_integration_status()
                self.integration_status_widget.update_from_integration_status(integration_status)
            except Exception as e:
                # Fall back to plan context if service fails
                self._update_from_plan_context()
        else:
            # Fall back to creating status from plan context
            self._update_from_plan_context()
        
        # Update plan context widget
        self.plan_context_widget.update_from_plan_context(self.plan_context)
    
    def _update_from_plan_context(self) -> None:
        """Update integration status widget from plan context data."""
        from ..services.integration_status_service import IntegrationStatus
        
        # Create integration status from plan context data
        integration_status = IntegrationStatus(
            config_loaded=self.plan_context.config_loaded,
            config_path=self.plan_context.config_path,
            config_summary=self.plan_context.config_summary,
            api_connected=self.plan_context.api_connected,
            api_response_time=self.plan_context.api_response_time,
            account_info=getattr(self.plan_context, 'account_info', None),
            mcp_status=self.plan_context.mcp_status,
            mcp_config_path=self.plan_context.mcp_config_path,
            integration_ready=bool(self.plan_context.next_task),  # Assume ready if we have a task
            status_message=self.plan_context.advised_action
        )
        
        self.integration_status_widget.update_from_integration_status(integration_status)
    
    def action_quit(self) -> None:
        """Quit the application."""
        self.exit()


class PlanContextWidget(Vertical):
    """A widget that displays plan context information."""
    
    DEFAULT_CSS = """
    PlanContextWidget {
        height: auto;
        border: solid purple;
        margin: 1;
        padding: 1;
    }
    
    PlanContextWidget > Static {
        height: auto;
        margin: 0;
        padding: 0;
    }
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.content_text = Static("Plan context loading...", id="plan_context_content")
        
    def compose(self):
        """Compose the plan context widget layout."""
        yield Static("📋 Plan Context", classes="widget_title")
        yield Static("─" * 20)
        yield self.content_text
    
    def update_from_plan_context(self, plan_context) -> None:
        """Update the widget based on plan context.
        
        Args:
            plan_context: PlanContext object from plan_context_service
        """
        lines = []
        
        if plan_context.next_task:
            task = plan_context.next_task
            lines.append(f"🎯 Next Task: {task.task_designator}")
            lines.append(f"📝 {task.name}")
            lines.append(f"📊 Status: {task.status}")
        else:
            lines.append("ℹ️ No tasks available")
        
        lines.append("")
        lines.append(f"💡 Action: {plan_context.advised_action}")
        lines.append("")
        lines.append(f"⏰ Updated: {plan_context.timestamp}")
        
        self.content_text.update("\n".join(lines))


class SetupApp(App):
    """TUI application for the setup command."""
    
    def __init__(self, config_service: ConfigurationService, project_root: Path, **kwargs):
        super().__init__(**kwargs)
        self.config_service = config_service
        self.project_root = project_root
    
    def on_mount(self) -> None:
        """Called when the app starts."""
        setup_screen = SetupScreen(
            config_service=self.config_service,
            project_root=self.project_root
        )
        self.push_screen(setup_screen)


 