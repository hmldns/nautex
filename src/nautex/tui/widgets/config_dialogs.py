"""Dialog widgets for configuration operations in the Nautex TUI."""

import asyncio
from pathlib import Path
from typing import Literal, Optional, Callable, List

from textual.widgets import Static, Button, Label, Select
from textual.containers import Horizontal, Vertical, Center, Middle
from textual.screen import Screen
from textual import events
from textual.reactive import reactive
from textual.widgets._select import NoSelection

from ...agent_setups.base import AgentRulesStatus
from ...models.config import AgentType
from ...services.mcp_config_service import MCPConfigService
from ...utils.mcp_utils import MCPConfigStatus
from ...services.agent_rules_service import AgentRulesService
from ...services.config_service import ConfigurationService
from ...services.integration_status_service import IntegrationStatusService
from ...utils import path2display


class ConfigWriteDialog(Screen):
    """Base class for configuration write dialogs."""

    DEFAULT_CSS = """
    ConfigWriteDialog {
        align: center middle;
    }

    #dialog {
        width: 60;
        height: auto;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }

    #title {
        text-align: center;
        text-style: bold;
        width: 100%;
        height: 1;
    }

    #message {
        height: auto;
        text-align: center;
        padding: 1;
    }

    #status {
        height: auto;
        text-align: center;
        padding: 1;
    }

    #path {
        height: auto;
        text-align: center;
        padding: 1;
    }

    #result {
        height: auto;
        text-align: center;
        padding: 1;
        color: $success;
    }

    #error {
        height: auto;
        text-align: center;
        padding: 1;
        color: $error;
    }

    #buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }

    Button {
        margin: 0 1;
        min-width: 8;
    }

    .success {
        color: $success;
    }

    .error {
        color: $error;
    }

    .warning {
        color: $warning;
    }
    """

    def __init__(self, title: str, message: str, **kwargs):
        super().__init__(**kwargs)
        self.title_text = title
        self.message_text = message
        self.status_text = ""
        self.info_text = ""
        self.result_text = ""
        self.error_text = ""
        self.button_handlers = {}

    def compose(self):
        """Compose the dialog layout."""
        with Center():
            with Middle():
                with Vertical(id="dialog"):
                    yield Static(self.title_text, id="title")
                    yield Static(self.message_text, id="message")
                    yield Static(self.status_text, id="status")
                    yield Static(self.info_text, id="path")
                    yield Static(self.result_text, id="result", classes="success")
                    yield Static(self.error_text, id="error", classes="error")
                    with Horizontal(id="buttons"):
                        for button_id, button_info in self.get_buttons().items():
                            yield Button(button_info["label"], id=button_id, variant=button_info.get("variant", "primary"))
                        yield Button("Close", id="close", variant="default")

    def get_buttons(self):
        """Get the buttons to display in the dialog. Override in subclasses."""
        return {}

    def register_button_handler(self, button_id: str, handler: Callable):
        """Register a handler for a button."""
        self.button_handlers[button_id] = handler

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "close":
            self.dismiss(False)
        elif event.button.id in self.button_handlers:
            handler = self.button_handlers[event.button.id]
            if asyncio.iscoroutinefunction(handler):
                # If the handler is async, create a task for it
                asyncio.create_task(handler())
            else:
                # If the handler is not async, call it directly
                handler()

    def on_key(self, event: events.Key) -> None:
        """Handle key events for keyboard shortcuts."""
        if event.key == "escape":
            event.stop()
            self.dismiss(False)

    def update_status_display(self, status_text: str = None, info_text: str = None):
        """Update status and information display.
        
        Args:
            status_text: The status text to display
            info_text: The information text to display
        """
        if status_text is not None:
            self.status_text = status_text
            try:
                self.query_one("#status", Static).update(status_text)
            except:
                pass

        if info_text is not None:
            self.info_text = info_text
            try:
                self.query_one("#path", Static).update(info_text)
            except:
                pass

    def update_result(self, success: bool, message: str):
        """Update the result message."""
        if success:
            self.result_text = message
            self.error_text = ""
            try:
                self.query_one("#result", Static).update(message)
                self.query_one("#error", Static).update("")
            except:
                pass
        else:
            self.result_text = ""
            self.error_text = message
            try:
                self.query_one("#result", Static).update("")
                self.query_one("#error", Static).update(message)
            except:
                pass

    def write_config(self):
        """Write the configuration. Override in subclasses."""
        pass


class MCPConfigWriteDialog(ConfigWriteDialog):
    """Dialog for writing MCP configuration."""

    def __init__(self, mcp_service: MCPConfigService, **kwargs):
        self.mcp_service = mcp_service
        
        # Initialize with default values
        self.mcp_status = MCPConfigStatus.NOT_FOUND
        self.mcp_path = None
        
        super().__init__(
            title="Manage MCP Configuration",
            message="Configure MCP integration for your agent",
            **kwargs
        )
        
        # Set initial status text
        self.status_text = "Loading configuration status..."
        self.info_text = "Please wait..."
        
        # Register button handlers
        self.register_button_handler("write_config", self.write_config)
        self.register_button_handler("update_config", self.write_config)
        
    async def on_mount(self) -> None:

        # Load current status
        self.mcp_status, self.mcp_path = await self.mcp_service.check_mcp_configuration()
        
        # Update status display
        status_text = self._format_status_text(self.mcp_status)
        info_text = await self._format_info_text(self.mcp_status, self.mcp_path)
        self.update_status_display(status_text=status_text, info_text=info_text)

    def _format_status_text(self, status: MCPConfigStatus) -> str:
        """Format status text based on MCP status."""
        if status == MCPConfigStatus.OK:
            return f"Status: [green]OK[/green] - MCP configuration is properly set up"
        elif status == MCPConfigStatus.MISCONFIGURED:
            return f"Status: [yellow]MISCONFIGURED[/yellow] - MCP configuration exists but is incorrect"
        else:  # NOT_FOUND
            return f"Status: [red]NOT FOUND[/red] - MCP configuration not found"

    async def _format_info_text(self, status: MCPConfigStatus, path: Optional[Path]) -> str:
        """Format information text based on current MCP configuration."""
        return await self.mcp_service.get_configuration_info()

    def get_buttons(self):
        """Get the buttons to display in the dialog based on current state."""
        if self.mcp_status in [MCPConfigStatus.OK, MCPConfigStatus.MISCONFIGURED]:
            return {
                "update_config": {
                    "label": "Update Configuration",
                    "variant": "primary"
                }
            }
        else:
            return {
                "write_config": {
                    "label": "Create Configuration",
                    "variant": "primary"
                }
            }

    async def write_config(self):
        """Write the MCP configuration."""
        success = await self.mcp_service.write_mcp_configuration()
        if success:
            self.update_result(True, "Successfully wrote MCP configuration")
            # Refresh status after successful write
            self.mcp_status, self.mcp_path = await self.mcp_service.check_mcp_configuration()
            info_text = await self._format_info_text(self.mcp_status, self.mcp_path)
            self.update_status_display(
                status_text=self._format_status_text(self.mcp_status),
                info_text=info_text
            )
        else:
            self.update_result(False, "Failed to write MCP configuration")


class AgentSelectionDialog(ConfigWriteDialog):
    """Dialog for selecting and configuring an agent."""

    def __init__(self, config_service: ConfigurationService,
                 integration_status_service: IntegrationStatusService, **kwargs):

        # Load current data first
        self.config_service = config_service
        self.integration_status_service = integration_status_service
        self.agent_types = config_service.get_supported_agent_types()

        current_agent = config_service.config.agent_type
        status_text = f"Current agent: [green]{current_agent}[/green]" if current_agent != AgentType.NOT_SELECTED else "No agent selected"

        super().__init__(
            title="Select Agent",
            message="Choose an AI agent to guide:",
            **kwargs
        )

        # Set initial data
        self.current_agent_type = current_agent
        self.selected_agent_type = current_agent
        self.status_text = status_text

        # Register button handlers
        self.register_button_handler("select_agent", self.select_agent_type)

    def compose(self):
        """Compose the dialog layout."""
        with Center():
            with Middle():
                with Vertical(id="dialog"):
                    yield Static(self.title_text, id="title")
                    yield Static(self.message_text, id="message")
                    yield Static(self.status_text, id="status")

                    # Agent type selection dropdown
                    agent_options = [(agent_type.display_name(), agent_type) for agent_type in self.agent_types]
                    yield Select(
                        options=agent_options,
                        value=self.current_agent_type if self.current_agent_type != AgentType.NOT_SELECTED else Select.BLANK,
                        id="agent_select"
                    )

                    yield Static(self.result_text, id="result", classes="success")
                    yield Static(self.error_text, id="error", classes="error")

                    with Horizontal(id="buttons"):
                        for button_id, button_info in self.get_buttons().items():
                            yield Button(button_info["label"], id=button_id, variant=button_info.get("variant", "primary"))
                        yield Button("Close", id="close", variant="default")

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle select change events."""
        if event.select.id == "agent_select":
            self.selected_agent_type = event.value

    def get_buttons(self):
        """Get the buttons to display in the dialog."""
        return {
            "select_agent": {
                "label": "Select Agent",
                "variant": "primary"
            }
        }

    def select_agent_type(self):
        """Save the selected agent type to the configuration."""
        try:
            # Update the configuration
            config = self.config_service.config
            config.agent_type = self.selected_agent_type

            # Save the configuration
            self.config_service.save_configuration(config)

            self.update_result(True, f"Successfully selected agent: {self.selected_agent_type}")

            # Update current agent type display
            self.current_agent_type = self.selected_agent_type
            status_text = f"Current agent: [green]{self.selected_agent_type}[/green]"
            self.update_status_display(status_text=status_text)

            # Close dialog after successful selection
            # self.app.call_later(self.dismiss, True)
            self.dismiss(True)
        except Exception as e:
            self.update_result(False, f"Failed to select agent: {e}")


class AgentRulesWriteDialog(ConfigWriteDialog):
    """Dialog for writing agent rules."""

    def __init__(self, rules_service: AgentRulesService, **kwargs):
        # Load current status first
        self.rules_service = rules_service
        rules_status, rules_path = rules_service.validate_rules()
        rules_info = rules_service.get_rules_info()

        # Prepare initial content
        status_text = self._format_status_text(rules_status)

        super().__init__(
            title="Manage Agent Rules",
            message="Configure workflow rules for your agent",
            **kwargs
        )

        # Set initial data
        self.rules_status = rules_status
        self.rules_path = rules_path
        self.status_text = status_text
        self.info_text = rules_info

        # Register button handlers
        self.register_button_handler("write_rules", self.write_config)
        self.register_button_handler("update_rules", self.write_config)

    def _format_status_text(self, status: AgentRulesStatus) -> str:
        """Format status text based on rules status."""
        if status == AgentRulesStatus.OK:
            return f"Status: [green]OK[/green] - Agent rules are properly set up"
        elif status == AgentRulesStatus.OUTDATED:
            return f"Status: [yellow]OUTDATED[/yellow] - Agent rules exist but are outdated"
        elif status == AgentRulesStatus.IOERROR:
            return f"Status: [red]ERROR[/red] - IO Error accessing rules file"
        else:  # NOT_FOUND
            return f"Status: [red]NOT FOUND[/red] - Agent rules not found"

    def get_buttons(self):
        """Get the buttons to display in the dialog based on current state."""
        if self.rules_status == AgentRulesStatus.OK:
            return {
                "update_rules": {
                    "label": "Update Rules",
                    "variant": "primary"
                }
            }
        elif self.rules_status == AgentRulesStatus.OUTDATED:
            return {
                "update_rules": {
                    "label": "Update Rules",
                    "variant": "warning"
                }
            }
        else:  # NOT_FOUND or IOERROR
            return {
                "write_rules": {
                    "label": "Write Rules",
                    "variant": "primary"
                }
            }

    def write_config(self):
        """Write the agent rules."""
        success = self.rules_service.ensure_rules()
        if success:
            self.update_result(True, "Successfully wrote agent rules")
            # Refresh status after successful write
            self.rules_status, self.rules_path = self.rules_service.validate_rules()
            rules_info = self.rules_service.get_rules_info()
            self.update_status_display(
                status_text=self._format_status_text(self.rules_status),
                info_text=rules_info
            )
        else:
            self.update_result(False, "Failed to write agent rules")