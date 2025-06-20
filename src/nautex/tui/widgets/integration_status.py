"""Status-related widgets for the Nautex TUI."""
from time import monotonic

from textual.reactive import reactive
from textual.widgets import Static, Button, Digits
from textual.containers import Horizontal, HorizontalGroup

from src.nautex.services.mcp_config_service import MCPConfigStatus
from src.nautex.models.integration_status import IntegrationStatus


class StatusDisplay(Static):
    """A read-only display for a single status item."""

    DEFAULT_CSS = """
    StatusDisplay {
        height: auto;
        width: auto;
        margin: 0 1 0 0;
        padding: 0;
        min-width: 10;
    }
    """

    def __init__(self, label: str, status: str = "⚪", **kwargs):
        """Initialize status display.

        Args:
            label: The label text
            status: The status indicator (emoji)
        """
        super().__init__(f"{status} {label}", **kwargs)
        self.label_text = label
        self.status_indicator = status

    def update_status(self, status: str) -> None:
        """Update the status indicator.

        Args:
            status: New status indicator
        """
        self.status_indicator = status
        self.update(f"{status} {self.label_text}")


class IntegrationStatusPanel(HorizontalGroup):
    """A horizontal strip of StatusDisplay widgets for integration status."""
    #
    DEFAULT_CSS = """
    IntegrationStatusPanel {
        width: 1fr;
        height: auto;
        width: 100%;
        border: solid $primary;
    }

    IntegrationStatusPanel StatusDisplay {
        height: auto;
        margin: 0 1 0 0;
        padding: 1 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.status_network = StatusDisplay("net", "⚪")
        self.status_api = StatusDisplay("api", "⚪")
        self.status_project = StatusDisplay("proj", "⚪")
        self.status_plan = StatusDisplay("plan", "⚪")
        self.status_mcp = StatusDisplay("mcp", "⚪")


        self.border_title = "Integration Status"

    def compose(self):
        """Compose the status panel layout."""
        yield self.status_network
        yield self.status_api
        yield self.status_project
        yield self.status_plan
        yield self.status_mcp


    def update_from_integration_status(self, integration_status: IntegrationStatus) -> None:
        # Network status

        self.status_network.update_status("🟢" if integration_status.network_connected else "🔴")

        # self.update_status("network", "🟢" if integration_status.network_connected
        # else "🔴" if integration_status.config_loaded and integration_status.config_summary and integration_status.config_summary.get(
        #     "has_token")
        # else "⚪")
        #
        # # API status
        # self.update_status("api", "🟢" if integration_status.api_connected
        # else "🔴" if integration_status.config_loaded and integration_status.config_summary and integration_status.config_summary.get(
        #     "has_token") and integration_status.network_connected
        # else "⚪")
        #
        # # Project status
        # self.update_status("project",
        #                    "🟢" if integration_status.config_summary and integration_status.config_summary.get(
        #                        "project_id")
        #                    else "⚪")
        #
        # # Plan status
        # self.update_status("plan",
        #                    "🟢" if integration_status.config_summary and integration_status.config_summary.get("plan_id")
        #                    else "⚪")
        #
        # # MCP status
        # self.update_status("mcp", "🟢" if integration_status.mcp_status == MCPConfigStatus.OK
        # else "🔴" if integration_status.mcp_status == MCPConfigStatus.MISCONFIGURED
        # else "⚪")
