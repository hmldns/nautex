"""Dialog widgets for configuration operations in the Nautex TUI."""

from pathlib import Path
from typing import Literal, Optional, Callable

from textual.widgets import Static, Button, Label
from textual.containers import Horizontal, Vertical, Center, Middle
from textual.screen import Screen
from textual import events
from textual.reactive import reactive

from ...services.mcp_config_service import MCPConfigService, MCPConfigStatus
from ...services.agent_rules_service import AgentRulesService, AgentRulesStatus


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
        self.result_text = ""
        self.error_text = ""
        self.path_text = ""
        self.status_text = ""
        self.button_handlers = {}

    def compose(self):
        """Compose the dialog layout."""
        with Center():
            with Middle():
                with Vertical(id="dialog"):
                    yield Static(self.title_text, id="title")
                    yield Static(self.message_text, id="message")
                    yield Static(self.status_text, id="status")
                    yield Static(self.path_text, id="path")
                    yield Static(self.result_text, id="result", classes="success")
                    yield Static(self.error_text, id="error", classes="error")
                    with Horizontal(id="buttons"):
                        for button_id, button_info in self.get_buttons().items():
                            yield Button(button_info["label"], id=button_id, variant=button_info.get("variant", "primary"))
                        yield Button("Cancel", id="cancel", variant="default")

    def get_buttons(self):
        """Get the buttons to display in the dialog.

        Returns:
            A dictionary mapping button IDs to button information.
            Each button info is a dictionary with keys:
            - label: The button label
            - variant: The button variant (default: "primary")

        This method should be overridden by subclasses to define their own buttons.
        """
        return {}

    def register_button_handler(self, button_id: str, handler: Callable):
        """Register a handler for a button.

        Args:
            button_id: The ID of the button
            handler: The handler function to call when the button is pressed
        """
        self.button_handlers[button_id] = handler

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "cancel":
            self.dismiss(False)
        elif event.button.id in self.button_handlers:
            self.button_handlers[event.button.id]()

    def on_key(self, event: events.Key) -> None:
        """Handle key events for keyboard shortcuts."""
        if event.key == "escape":
            self.dismiss(False)

    def write_config(self):
        """Write the configuration. To be implemented by subclasses."""
        pass

    def update_result(self, success: bool, message: str):
        """Update the result message."""
        if success:
            self.result_text = message
            self.error_text = ""
        else:
            self.result_text = ""
            self.error_text = message
        self.refresh()


class MCPConfigWriteDialog(ConfigWriteDialog):
    """Dialog for writing MCP configuration."""

    def __init__(self, mcp_service: MCPConfigService, **kwargs):
        super().__init__(
            title="Write MCP Configuration",
            message="Configure MCP integration for IDE tools like Cursor.",
            **kwargs
        )
        self.mcp_service = mcp_service

        # Get current status
        self.status, self.path = self.mcp_service.check_mcp_configuration()

        # Set status text
        if self.status == MCPConfigStatus.OK:
            self.status_text = f"Status: [green]OK[/green] - MCP configuration is properly set up"
        elif self.status == MCPConfigStatus.MISCONFIGURED:
            self.status_text = f"Status: [yellow]MISCONFIGURED[/yellow] - MCP configuration exists but is incorrect"
        else:  # NOT_FOUND
            self.status_text = f"Status: [red]NOT FOUND[/red] - MCP configuration not found"

        # Set path text
        if self.path:
            self.path_text = f"Current path: {self.path}"
        else:
            path = self.mcp_service.get_config_path()
            self.path_text = f"Will be written to: {path}"

        # Register button handlers
        self.register_button_handler("write_config", self.write_config)
        self.register_button_handler("update_config", self.write_config)

    def get_buttons(self):
        """Get the buttons to display in the dialog based on current state."""
        if self.status in [MCPConfigStatus.OK, MCPConfigStatus.MISCONFIGURED]:
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

    def write_config(self):
        """Write the MCP configuration."""
        success = self.mcp_service.write_mcp_configuration('local')
        if success:
            self.update_result(True, f"Successfully wrote MCP configuration")
        else:
            self.update_result(False, f"Failed to write MCP configuration")


class AgentRulesWriteDialog(ConfigWriteDialog):
    """Dialog for writing agent rules."""

    def __init__(self, rules_service: AgentRulesService, **kwargs):
        super().__init__(
            title="Write Agent Rules",
            message="Configure agent workflow rules for tools like Cursor.",
            **kwargs
        )
        self.rules_service = rules_service

        # Get current status
        self.status, self.path = self.rules_service.check_rules_file()

        # Set status text
        if self.status == AgentRulesStatus.OK:
            self.status_text = f"Status: [green]OK[/green] - Agent rules are properly set up"
        elif self.status == AgentRulesStatus.OUTDATED:
            self.status_text = f"Status: [yellow]OUTDATED[/yellow] - Agent rules exist but are outdated"
        else:  # NOT_FOUND
            self.status_text = f"Status: [red]NOT FOUND[/red] - Agent rules not found"

        # Set path text
        if self.path:
            self.path_text = f"Current path: {self.path}"
        else:
            path = self.rules_service.get_rules_path()
            self.path_text = f"Will be written to: {path}"

        # Register button handlers
        self.register_button_handler("write_rules", self.write_config)
        self.register_button_handler("update_rules", self.write_config)

    def get_buttons(self):
        """Get the buttons to display in the dialog based on current state."""
        if self.status == AgentRulesStatus.OK:
            return {
                "update_rules": {
                    "label": "Update Rules",
                    "variant": "primary"
                }
            }
        elif self.status == AgentRulesStatus.OUTDATED:
            return {
                "update_rules": {
                    "label": "Update Rules",
                    "variant": "warning"
                }
            }
        else:  # NOT_FOUND
            return {
                "write_rules": {
                    "label": "Write Rules",
                    "variant": "primary"
                }
            }

    def write_config(self):
        """Write the agent rules."""
        success = self.rules_service.write_rules_file('local')
        if success:
            self.update_result(True, f"Successfully wrote agent rules")
        else:
            self.update_result(False, f"Failed to write agent rules")
