"""System information widget for displaying host, email, and network stats."""

from typing import Optional
from textual.widgets import DataTable, Static
from textual.containers import Vertical
from textual.reactive import reactive

from ...services.config_service import ConfigurationService
from ...services.integration_status_service import IntegrationStatusService
from ...models.config_models import NautexConfig
from ...models.integration_status import IntegrationStatus


class SystemInfoWidget(Vertical):
    """Widget displaying system information in a DataTable format."""

    DEFAULT_CSS = """
    SystemInfoWidget {
        height: auto;
        width: 50;
        min-height: 8;
        max-height: 14;
        border: solid $primary;
        margin: 0 0 1 0;
        padding: 1;
    }

    SystemInfoWidget DataTable {
        height: 1fr;
        border: none;
    }

    SystemInfoWidget Static {
        height: auto;
        margin: 0 0 1 0;
        text-style: bold;
    }
    """

    # Reactive properties
    host: reactive[str] = reactive("")
    email: reactive[str] = reactive("")
    network_delay: reactive[float] = reactive(0.0)

    def __init__(
        self,
        **kwargs
    ):
        """Initialize the SystemInfoWidget."""
        super().__init__(**kwargs)


        self.border_title = "System Information"

        # Create data table - defer column setup until mount
        self.data_table = DataTable(show_header=False, show_row_labels=False)
        self._table_initialized = False

    def compose(self):
        """Compose the widget layout."""

        yield self.data_table

    async def on_mount(self) -> None:
        """Called when the widget is mounted."""
        # Initialize the table structure - this is safe now that we're in an app context
        if not self._table_initialized:
            self.data_table.add_columns("Property", "Value")
            self._table_initialized = True

        self._setup_table()

    def _setup_table(self) -> None:
        """Set up the data table with initial rows."""
        # Clear existing rows
        self.data_table.clear()

        # Add rows for each system info item
        self.data_table.add_row("Host", self.host or "Not configured")
        self.data_table.add_row("Acc Email", self.email or "Not available")
        self.data_table.add_row("ping", f"{self.network_delay:.3f}s" if self.network_delay > 0 else "N/A")


    async def refresh_data(self) -> None:
        """Refresh the system information data.

        This method is a placeholder. The widget should be updated using update_system_info directly.
        """
        # This method is intentionally left empty as per the issue requirements.
        # The widget should be updated using update_system_info directly.
        pass

    def update_system_info(
        self,
        *,
        host: Optional[str] = None,
        email: Optional[str] = None,
        network_delay: Optional[float] = None,
    ) -> None:
        # Update reactive properties
        if host is not None:
            self.host = host
        if email is not None:
            self.email = email
        if network_delay is not None:
            self.network_delay = network_delay

        # Update table display
        try:
            # Update host row
            self.data_table.update_cell_at((0, 1), self.host or "Not configured", update_width=True)
            # Update email row
            self.data_table.update_cell_at((1, 1), self.email or "Not available", update_width=True)

            # Update network delay row
            network_delay_text = f"{self.network_delay:.3f}s" if self.network_delay > 0.0 else "N/A"
            self.data_table.update_cell_at((2, 1), network_delay_text, update_width=True)

        except Exception:
            # If table update fails, rebuild it
            self._setup_table()
