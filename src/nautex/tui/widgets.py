"""Reusable TUI widgets for the Nautex CLI."""

from textual.widgets import Static, Input, Label, OptionList, Button
from textual.containers import Horizontal, Vertical, Center, Middle
from textual.screen import Screen
from textual import events
from textual.reactive import reactive
from textual.widgets import Link


class StatusDisplay(Static):
    """A read-only display for a single status item."""
    
    DEFAULT_CSS = """
    StatusDisplay {
        height: auto;
        width: auto;
        margin: 0 1 0 0;
        padding: 0;
        min-width: 12;
    }
    """
    
    def __init__(self, label: str, status: str = "⚪", **kwargs):
        """Initialize status display.
        
        Args:
            label: The label text
            status: The status indicator (emoji)
        """
        super().__init__(f"({status}) {label}", **kwargs)
        self.label_text = label
        self.status_indicator = status
    
    def update_status(self, status: str) -> None:
        """Update the status indicator.
        
        Args:
            status: New status indicator
        """
        self.status_indicator = status
        self.update(f"({status}) {self.label_text}")


class SetupStatusPanel(Horizontal):
    """A horizontal strip of StatusDisplay widgets for setup progress."""
    
    DEFAULT_CSS = """
    SetupStatusPanel {
        height: auto;
        width: 100%;
        margin: 0 0 1 0;
        padding: 0;
        border: solid $primary;
    }
    
    SetupStatusPanel > StatusDisplay {
        height: auto;
        margin: 0 1 0 0;
        padding: 0 1;
    }
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.statuses = {
            "network": StatusDisplay("network", "⚪"),
            "api": StatusDisplay("api", "⚪"),
            "project": StatusDisplay("project", "⚪"),  
            "plan": StatusDisplay("plan", "⚪"),
            "mcp": StatusDisplay("mcp", "⚪"),
        }
    
    def compose(self):
        """Compose the status panel layout."""
        for status_widget in self.statuses.values():
            yield status_widget
    
    def update_status(self, key: str, status: str) -> None:
        """Update a specific status indicator.
        
        Args:
            key: The status key
            status: New status indicator (🟢, 🔴, 🟡, ⚪)
        """
        if key in self.statuses:
            self.statuses[key].update_status(status)
    
    def update_from_integration_status(self, integration_status) -> None:
        """Update status indicators based on integration status service data.
        
        Args:
            integration_status: IntegrationStatus object from integration_status_service
        """
        # Network status (based on API connectivity attempt)
        if integration_status.api_connected:
            self.update_status("network", "🟢")
        elif integration_status.config_loaded and integration_status.config_summary and integration_status.config_summary.get("has_token"):
            # Have token but not connected - network issue
            self.update_status("network", "🔴")
        else:
            self.update_status("network", "⚪")
            
        # API status (based on API authentication)
        if integration_status.api_connected:
            self.update_status("api", "🟢")
        elif integration_status.config_loaded and integration_status.config_summary and integration_status.config_summary.get("has_token"):
            # Have token but connection failed - API issue
            self.update_status("api", "🔴")
        else:
            self.update_status("api", "⚪")
            
        # Project status
        if integration_status.config_summary and integration_status.config_summary.get("project_id"):
            self.update_status("project", "🟢")
        else:
            self.update_status("project", "⚪")
            
        # Plan status  
        if integration_status.config_summary and integration_status.config_summary.get("plan_id"):
            self.update_status("plan", "🟢")
        else:
            self.update_status("plan", "⚪")
            
        # MCP status (from integration service)
        if hasattr(integration_status, 'mcp_status'):
            from ..models.api_models import MCPConfigStatus
            if integration_status.mcp_status == MCPConfigStatus.OK:
                self.update_status("mcp", "🟢")
            elif integration_status.mcp_status == MCPConfigStatus.MISCONFIGURED:
                self.update_status("mcp", "🔴")
            else:  # NOT_FOUND
                self.update_status("mcp", "⚪")


class IntegrationStatusWidget(Vertical):
    """A comprehensive status widget tied to the integration status service."""
    
    DEFAULT_CSS = """
    IntegrationStatusWidget {
        height: auto;
        border: solid blue;
        margin: 1;
        padding: 1;
    }
    
    IntegrationStatusWidget > Static {
        height: auto;
        margin: 0;
        padding: 0;
    }
    
    IntegrationStatusWidget > SetupStatusPanel {
        height: auto;
        margin: 1 0;
        padding: 0;
    }
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.status_panel = SetupStatusPanel()
        self.status_text = Static("Checking integration status...", id="status_text")
        
    def compose(self):
        """Compose the integration status widget layout."""
        yield Static("Integration Status", classes="widget_title")
        yield self.status_panel
        yield Static("─" * 30)
        yield self.status_text
    
    def update_from_integration_status(self, integration_status) -> None:
        """Update the widget based on integration status.
        
        Args:
            integration_status: IntegrationStatus object from integration_status_service
        """
        self.status_panel.update_from_integration_status(integration_status)
        
        # Update status text
        if integration_status.integration_ready:
            self.status_text.update("✅ Ready to work!")
        else:
            self.status_text.update(f"⚠️ {integration_status.status_message}")


class AccountStatusPanel(Static):
    """A read-only display for validated account information."""
    
    DEFAULT_CSS = """
    AccountStatusPanel {
        height: auto;
        border: solid green;
        margin: 1;
        padding: 1;
    }
    """
    
    def __init__(self, **kwargs):
        super().__init__("Account information will appear here", **kwargs)
    
    def show_account_info(self, email: str, api_version: str, latency: float = None) -> None:
        """Display account information.
        
        Args:
            email: Profile email
            api_version: API version
            latency: Response latency in seconds
        """
        lines = ["📊 API Info"]
        lines.append("─" * 12)
        lines.append(f"Email: {email}")
        lines.append(f"API Version: {api_version}")
        if latency is not None:
            lines.append(f"Latency: {latency:.3f}s")
        self.update("\n".join(lines))


class StepByStepLayout(Vertical):
    """A layout that shows widgets step by step during setup."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.widgets_registry = {}
        
    def register_widget(self, step_name: str, widget):
        """Register a widget for a specific step.
        
        Args:
            step_name: Name of the setup step
            widget: Widget to show for that step
        """
        self.widgets_registry[step_name] = widget
        widget.display = False  # Hide initially
        
    def show_step(self, step_name: str):
        """Show widgets for a specific step.
        
        Args:
            step_name: Name of the step to show
        """
        # Hide all widgets first
        for widget in self.widgets_registry.values():
            widget.display = False
            
        # Show only the widgets for the current step and previous steps
        step_order = ["token", "agent_name", "validate", "projects", "plans", "summary"]
        current_index = step_order.index(step_name) if step_name in step_order else 0
        
        # Show widgets up to current step
        for i in range(current_index + 1):
            if i < len(step_order):
                step = step_order[i]
                if step in self.widgets_registry:
                    self.widgets_registry[step].display = True


class CompactHorizontalLayout(Horizontal):
    """A horizontal layout for side-by-side widgets."""
    
    DEFAULT_CSS = """
    CompactHorizontalLayout {
        height: auto;
        margin: 1 0;
    }
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class ConfigurationSummaryView(Static):
    """A read-only view of the full configuration."""
    
    def __init__(self, **kwargs):
        super().__init__("Configuration summary will appear here", **kwargs)
    
    def show_config(self, config_data: dict) -> None:
        """Display configuration summary.
        
        Args:
            config_data: Configuration data to display
        """
        lines = []
        lines.append("📋 Configuration Summary")
        lines.append("=" * 25)
        
        for key, value in config_data.items():
            # Format the key nicely
            display_key = key.replace('_', ' ').title()
            
            # Handle different value types
            if isinstance(value, bool):
                display_value = "✅ Yes" if value else "❌ No"
            elif isinstance(value, str) and value:
                # Mask sensitive values
                if any(sensitive in key.lower() for sensitive in ['token', 'key', 'password']):
                    display_value = "*" * min(len(value), 8) + "..."
                else:
                    display_value = value
            elif isinstance(value, (int, float)):
                display_value = str(value)
            elif value is None:
                display_value = "Not set"
            else:
                display_value = str(value)
            
            lines.append(f"{display_key}: {display_value}")
        
        self.update("\n".join(lines))


class CompactInput(Vertical):
    """A compact input field with minimal spacing."""
    
    DEFAULT_CSS = """
    CompactInput {
        height: auto;
        margin: 0;
        padding: 0;
    }
    
    CompactInput > Label {
        margin: 0 0 1 0;
        padding: 0;
        height: 1;
    }
    
    CompactInput > Input {
        margin: 0;
        padding: 0;
        height: 3;
    }
    """
    
    def __init__(self, title: str, placeholder: str = "", **kwargs):
        super().__init__(**kwargs)
        self.title_label = Label(title)
        self.input_field = Input(placeholder=placeholder)
    
    def compose(self):
        """Compose the compact input layout."""
        yield self.title_label
        yield self.input_field
    
    @property
    def value(self) -> str:
        """Get the input value."""
        return self.input_field.value
    
    def set_value(self, value: str) -> None:
        """Set the input value."""
        self.input_field.value = value
    
    def focus(self) -> None:
        """Focus the input field."""
        self.input_field.focus()


class ApiTokenInput(Vertical):
    """A compact API token input with help text and link."""
    
    DEFAULT_CSS = """
    ApiTokenInput {
        height: auto;
        margin: 0;
        padding: 0;
    }
    
    ApiTokenInput > Label {
        margin: 0 0 1 0;
        padding: 0;
        height: 1;
    }
    
    ApiTokenInput > Input {
        margin: 0;
        padding: 0;
        height: 3;
    }
    
    ApiTokenInput > Static {
        height: 1;
        margin: 1 0 0 0;
        padding: 0;
        color: $text-muted;
    }
    """
    
    def __init__(self, title: str = "API Token", placeholder: str = "Enter your Nautex.ai API token...", **kwargs):
        super().__init__(**kwargs)
        self.title_label = Label(title)
        self.input_field = Input(placeholder=placeholder)
        self.help_text = Static("Get your API token from: [link=https://app.nautex.ai/new_token]app.nautex.ai/new_token[/link]", markup=True)
    
    def compose(self):
        """Compose the API token input layout."""
        yield self.title_label
        yield self.input_field
        yield self.help_text
    
    @property
    def value(self) -> str:
        """Get the input value."""
        return self.input_field.value
    
    def set_value(self, value: str) -> None:
        """Set the input value."""
        self.input_field.value = value
    
    def focus(self) -> None:
        """Focus the input field."""
        self.input_field.focus()


class TitledInput(Vertical):
    """An input field with a title and optional validation state."""
    
    def __init__(self, title: str, placeholder: str = "", **kwargs):
        super().__init__(**kwargs)
        self.title_label = Label(title)
        self.input_field = Input(placeholder=placeholder)
    
    def compose(self):
        """Compose the input layout."""
        yield self.title_label
        yield self.input_field
    
    @property
    def value(self) -> str:
        """Get the input value."""
        return self.input_field.value
    
    def set_value(self, value: str) -> None:
        """Set the input value."""
        self.input_field.value = value


class TitledOptionList(Vertical):
    """An option list with a title, loading indicator, and disabled state."""
    
    def __init__(self, title: str, **kwargs):
        super().__init__(**kwargs)
        self.title_label = Label(title)
        self.option_list = OptionList()
        self.loading_label = Label("Loading...")
        self._is_loading = True
    
    def compose(self):
        """Compose the option list layout."""
        yield self.title_label
        yield self.loading_label
        yield self.option_list
    
    def on_mount(self):
        """Called when the widget is mounted."""
        self._update_display()
    
    def set_loading(self, loading: bool) -> None:
        """Set loading state.
        
        Args:
            loading: Whether the list is loading
        """
        self._is_loading = loading
        self._update_display()
    
    def set_options(self, options: list) -> None:
        """Set the available options.
        
        Args:
            options: List of option strings
        """
        self.option_list.clear_options()
        for option in options:
            self.option_list.add_option(option)
        self.set_loading(False)
    
    def _update_display(self) -> None:
        """Update the display based on loading state."""
        self.loading_label.display = self._is_loading
        self.option_list.display = not self._is_loading


class ConfirmationDialog(Screen):
    """A modal screen for yes/no confirmation."""
    
    DEFAULT_CSS = """
    ConfirmationDialog {
        align: center middle;
    }
    
    #dialog {
        width: 50;
        height: 11;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }
    
    #message {
        height: 3;
        text-align: center;
        padding: 1;
    }
    
    #buttons {
        height: 3;
        align: center middle;
    }
    
    Button {
        margin: 0 1;
        min-width: 8;
    }
    """
    
    def __init__(self, message: str, title: str = "Confirm", **kwargs):
        super().__init__(**kwargs)
        self.message = message
        self.title = title
    
    def compose(self):
        """Compose the dialog layout."""
        with Center():
            with Middle():
                with Vertical(id="dialog"):
                    yield Static(self.title, id="title")
                    yield Static(self.message, id="message")
                    with Horizontal(id="buttons"):
                        yield Button("Yes", id="yes", variant="primary")
                        yield Button("No", id="no", variant="default")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "yes":
            self.dismiss(True)
        elif event.button.id == "no":
            self.dismiss(False)
    
    def on_key(self, event: events.Key) -> None:
        """Handle key events for keyboard shortcuts."""
        if event.key == "escape":
            self.dismiss(False)
        elif event.key == "enter":
            self.dismiss(True)
        elif event.key in ("y", "Y"):
            self.dismiss(True)
        elif event.key in ("n", "N"):
            self.dismiss(False)


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


# Global shared integration status widget instance
_shared_integration_status_widget = None

def get_shared_integration_status_widget():
    """Get the shared integration status widget instance.
    
    Returns:
        IntegrationStatusWidget: Shared widget instance
    """
    global _shared_integration_status_widget
    if _shared_integration_status_widget is None:
        _shared_integration_status_widget = IntegrationStatusWidget()
    return _shared_integration_status_widget 