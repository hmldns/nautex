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
        width: 40;
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
    api_delay: reactive[float] = reactive(0.0)
    network_status: reactive[str] = reactive("⚪")
    api_status: reactive[str] = reactive("⚪")

    def __init__(
        self,
        config_service: Optional[ConfigurationService] = None,
        integration_status_service: Optional[IntegrationStatusService] = None,
        **kwargs
    ):
        """Initialize the SystemInfoWidget.

        Args:
            config_service: Service for configuration management
            integration_status_service: Service for integration status
        """
        super().__init__(**kwargs)
        self.config_service = config_service
        self.integration_status_service = integration_status_service
        

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
        
        # Load initial data
        await self.refresh_data()

    def _setup_table(self) -> None:
        """Set up the data table with initial rows."""
        # Clear existing rows
        self.data_table.clear()
        
        # Add rows for each system info item
        self.data_table.add_row("Host", self.host or "Not configured")
        self.data_table.add_row("Acc Email", self.email or "Not available")
        self.data_table.add_row("ping", f"{self.network_delay:.3f}s" if self.network_delay > 0 else "N/A")


    async def refresh_data(self) -> None:
        """Refresh the system information data."""
        try:
            # Load configuration data
            if self.config_service:
                await self._load_config_data()
            
            # Load integration status data
            if self.integration_status_service:
                await self._load_integration_status_data()
                
            # Update the table display
            self._update_table_display()
            
        except Exception as e:
            # Handle errors gracefully
            self.log.error(f"Failed to refresh data: {e}")

    async def _load_config_data(self) -> None:
        """Load configuration data."""
        try:
            config = self.config_service.load_configuration()
            self.host = config.api_host if config.api_host else "Not configured"
        except Exception:
            self.host = "Configuration error"

    async def _load_integration_status_data(self) -> None:
        """Load integration status data."""
        try:
            status = await self.integration_status_service.get_integration_status()
            
            # Update email from account info
            if status.account_info and status.account_info.profile_email:
                self.email = status.account_info.profile_email
            else:
                self.email = "Not available"
            
            # Update network delay and status
            if hasattr(status, 'network_response_time') and status.network_response_time:
                self.network_delay = status.network_response_time
            else:
                self.network_delay = 0.0
            
            # Update API delay
            if status.api_response_time:
                self.api_delay = status.api_response_time
            else:
                self.api_delay = 0.0
            
            # Update status indicators
            if hasattr(status, 'network_connected'):
                if status.network_connected:
                    self.network_status = "🟢"
                elif hasattr(status, 'network_error') and status.network_error:
                    if 'timeout' in status.network_error.lower():
                        self.network_status = "🔴"
                    else:
                        self.network_status = "🟡"
                else:
                    self.network_status = "🔴"
            else:
                self.network_status = "⚪"
            
            if status.api_connected:
                self.api_status = "🟢"
            elif status.config_loaded and hasattr(status, 'network_connected') and not status.network_connected:
                self.api_status = "⚪"  # Can't test API without network
            else:
                self.api_status = "🔴"
                
        except Exception:
            self.email = "Status error"
            self.network_delay = 0.0
            self.api_delay = 0.0
            self.network_status = "❌"
            self.api_status = "❌"

    def _update_table_display(self) -> None:
        """Update the table display with current data."""
        # Get table rows
        try:
            # Update host row
            self.data_table.update_cell_at((0, 1), self.host or "Not configured")
            self.data_table.update_cell_at((0, 2), self.network_status)
            
            # Update email row
            self.data_table.update_cell_at((1, 1), self.email or "Not available")
            self.data_table.update_cell_at((1, 2), self.api_status)
            
            # Update network delay row
            network_delay_text = f"{self.network_delay:.3f}s" if self.network_delay > 0 else "N/A"
            self.data_table.update_cell_at((2, 1), network_delay_text)
            
            # Update API delay row
            api_delay_text = f"{self.api_delay:.3f}s" if self.api_delay > 0 else "N/A"
            self.data_table.update_cell_at((3, 1), api_delay_text)
            
        except Exception:
            # If table update fails, rebuild it
            self._setup_table()

    def update_host(self, host: str) -> None:
        """Update the host value and refresh display.
        
        Args:
            host: New host value
        """
        self.host = host
        try:
            self.data_table.update_cell_at((0, 1), host)
        except Exception:
            pass

    def update_email(self, email: str) -> None:
        """Update the email value and refresh display.
        
        Args:
            email: New email value
        """
        self.email = email
        try:
            self.data_table.update_cell_at((1, 1), email)
        except Exception:
            pass

    def update_network_delay(self, delay: float, status: str = "🟢") -> None:
        """Update the network delay and status.
        
        Args:
            delay: Network delay in seconds
            status: Status indicator (🟢, 🟡, 🔴, ⚪)
        """
        self.network_delay = delay
        self.network_status = status
        try:
            delay_text = f"{delay:.3f}s" if delay > 0 else "N/A"
            self.data_table.update_cell_at((2, 1), delay_text)
            self.data_table.update_cell_at((0, 2), status)
        except Exception:
            pass

    def update_api_delay(self, delay: float, status: str = "🟢") -> None:
        """Update the API delay and status.
        
        Args:
            delay: API delay in seconds
            status: Status indicator (🟢, 🟡, 🔴, ⚪)
        """
        self.api_delay = delay
        self.api_status = status
        try:
            delay_text = f"{delay:.3f}s" if delay > 0 else "N/A"
            self.data_table.update_cell_at((3, 1), delay_text)
            self.data_table.update_cell_at((1, 2), status)
        except Exception:
            pass 