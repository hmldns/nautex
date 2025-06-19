"""Loadable list widget for the Nautex TUI."""

import asyncio
from typing import Callable, List, Optional, Any

from textual.containers import Vertical, Horizontal
from textual.widgets import Static, Button, LoadingIndicator
from textual.reactive import reactive


class LoadableList(Vertical):
    """A list widget that can load data asynchronously and display a loading indicator."""

    DEFAULT_CSS = """
    LoadableList {
        height: auto;
        margin: 0;
        padding: 0;
        border: solid $primary;
    }

    /* ───────────────── title ───────────────── */
    LoadableList > .title-row {
        height: 1;
        margin: 0 0 1 0;
    }

    /* ───────────────── content ───────────────── */
    LoadableList > .content {
        height: auto;
        margin: 0;
        padding: 0 1;
    }

    LoadableList.disabled {
        opacity: 0.5;
    }

    LoadableList .list-item {
        height: 1;
        margin: 0;
        padding: 0;
    }

    LoadableList .loading-container {
        height: 3;
        align: center middle;
    }
    """

    # Reactive properties
    is_loading = reactive(False)
    is_disabled = reactive(False)

    def __init__(
        self,
        title: str,
        data_loader: Optional[Callable[[], Any]] = None,
        mock_data: Optional[List[str]] = None,
        **kwargs
    ):
        """Initialize the LoadableList widget.

        Args:
            title: The title of the list widget
            data_loader: A callable that returns data to be displayed in the list
            mock_data: Mock data to display in the list (used if data_loader is None)
        """
        super().__init__(**kwargs)
        self.border_title = title
        self.data_loader = data_loader
        self.mock_data = mock_data or ["Item 1", "Item 2", "Item 3"]

        # Create widgets
        self.loading_indicator = LoadingIndicator()
        self.content = Vertical(classes="content")
        self.items = []

    def compose(self):
        """Compose the loadable list layout."""
        # Set the border title
        self.styles.border_title = self.border_title

        with Vertical(classes="content"):
            # This will be populated with list items or loading indicator
            yield self.content

    def on_mount(self):
        """Called when the widget is mounted."""
        # Load initial data
        self.app.call_later(self.load_data)

    async def load_data(self):
        """Load data into the list."""
        # Show loading indicator
        self.is_loading = True
        await self.content.remove_children()

        # Create loading container and mount it directly
        loading_container = Horizontal(classes="loading-container")
        await self.content.mount(loading_container)
        await loading_container.mount(self.loading_indicator)

        # Load data (with artificial delay for testing)
        if self.data_loader:
            try:
                # Use lambda with sleep for testing
                await asyncio.sleep(1)  # 1 second delay for testing
                data = self.data_loader()
            except Exception:
                data = ["Error loading data"]
        else:
            # Use mock data with delay
            await asyncio.sleep(1)  # 1 second delay for testing
            data = self.mock_data

        # Update UI with data
        self.is_loading = False
        await self.content.remove_children()

        # Add items to the list
        self.items = []
        for item in data:
            item_widget = Static(str(item), classes="list-item")
            self.items.append(item_widget)
            await self.content.mount(item_widget)

    def toggle_disabled(self):
        """Toggle the disabled state of the widget."""
        self.is_disabled = not self.is_disabled
        if self.is_disabled:
            self.add_class("disabled")
        else:
            self.remove_class("disabled")

    def watch_is_disabled(self, is_disabled: bool):
        """React to changes in the disabled state."""
        if is_disabled:
            self.add_class("disabled")
        else:
            self.remove_class("disabled")
