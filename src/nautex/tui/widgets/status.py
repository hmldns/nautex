"""Status-related widgets for the Nautex TUI."""

from textual.widgets import Static
from textual.containers import Horizontal


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
            from nautex.models.api_models import MCPConfigStatus
            if integration_status.mcp_status == MCPConfigStatus.OK:
                self.update_status("mcp", "🟢")
            elif integration_status.mcp_status == MCPConfigStatus.MISCONFIGURED:
                self.update_status("mcp", "🔴")
            else:  # NOT_FOUND
                self.update_status("mcp", "⚪")


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