"""Loadable list widget for the Nautex TUI."""

import asyncio
from typing import Callable, List, Optional, Any, Union, Awaitable, Iterable

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Static, Button, LoadingIndicator, ListView, ListItem, Label
from textual.reactive import reactive
from textual.binding import Binding
from textual.message import Message


class LoadableList(Vertical):
    """A list widget that can load data asynchronously and display a loading indicator."""

    DEFAULT_CSS = """
    LoadableList {
        height: 1fr;
        margin: 0;
        padding: 0;
        border: solid $primary;
        border-bottom: solid $primary;
    }

    LoadableList.disabled {
        opacity: 0.5;
        border: solid $error;
        border-bottom: solid $error;
    }

    LoadableList .list-view > ListItem {
        height: 1;
        margin: 0;
        padding: 0 1;
    }

    LoadableList .loading-container {
        height: 3;
        align: center middle;
        background: $surface-lighten-1;
    }

    LoadableList .save-message {
        width: auto;
        align-horizontal: right;
        color: $text-muted;
        display: none;       /* shown only when value changes */
        margin-top: 0;
        height: 1;
        padding: 0 1;
    }
    """

    # Define a message class for selection changes
    class SelectionChanged(Message):
        """Message sent when the selection changes."""

        def __init__(self, sender, selected_item: Optional[Any] = None):
            self.selected_item = selected_item
            super().__init__()

    # Reactive properties
    is_loading = reactive(False)
    is_disabled = reactive(False)
    value_changed = reactive(False)

    def __init__(
        self,
        title: str,
        data_loader: Optional[Callable[[], Any]] = None,
        mock_data: Optional[List[str]] = None,
        on_change: Optional[Callable[[Any], Awaitable[None]]] = None,
        **kwargs
    ):
        """Initialize the LoadableList widget.

        Args:
            title: The title of the list widget
            data_loader: A callable that returns data to be displayed in the list
            mock_data: Mock data to display in the list (used if data_loader is None)
            on_change: Async callback function called when the selection changes and Enter is pressed
        """
        super().__init__(**kwargs)
        self.border_title = title
        self.data_loader = data_loader
        self.mock_data = mock_data or ["Item 1", "Item 2", "Item 3"]
        self.on_change = on_change

        # Create widgets
        self.loading_indicator = LoadingIndicator()
        self.save_message = Static("press enter to save", classes="save-message")
        self.save_message.display = False
        self.item_data = []

        # Create the ListView
        self.list_view = ListView(classes="list-view", initial_index=None)

    def compose(self) -> ComposeResult:
        """Compose the loadable list layout."""
        # Set the border title
        self.styles.border_title = self.border_title

        # Yield the ListView and the save message
        yield self.list_view
        yield self.save_message

    def on_mount(self):
        """Called when the widget is mounted."""
        # Load initial data
        self.app.call_later(self.load_data)

    def reload(self):
        """Reload the list data."""
        # Set loading state immediately to provide visual feedback
        self.is_loading = True
        # Schedule the load_data method to be called in the next event loop iteration
        self.app.call_later(self.load_data)

    async def load_data(self):
        """Load data into the list."""
        # Show loading state
        self.is_loading = True

        # Clear existing items
        await self.list_view.clear()

        # Create a loading indicator item with a clear label
        loading_container = Horizontal(classes="loading-container")
        loading_item = ListItem(loading_container)
        await self.list_view.append(loading_item)
        # Now that loading_container is mounted, we can mount the loading indicator to it
        await loading_container.mount(self.loading_indicator)

        # Add a "Loading..." label to make it more visible
        loading_label = ListItem(Label("Loading..."))
        await self.list_view.append(loading_label)

        # Check if the list is disabled
        if self.is_disabled:
            # If disabled, show a message and don't load data
            await asyncio.sleep(1)  # Short delay for visual feedback
            self.is_loading = False
            await self.list_view.clear()
            await self.list_view.append(ListItem(Label("List is disabled")))
            return

        # Load data (with artificial delay for testing)
        if self.data_loader:
            try:
                # Use lambda with sleep for testing
                await asyncio.sleep(1)  # 1 second delay for testing
                data = self.data_loader()
            except Exception as e:
                self.app.log(f"Error loading data: {str(e)}")
                data = ["Error loading data"]
        else:
            # Use mock data with delay
            await asyncio.sleep(1)  # 1 second delay for testing
            data = self.mock_data

        # Update UI with data
        self.is_loading = False

        # Clear the loading indicator
        await self.list_view.clear()

        # Add items to the list
        self.item_data = []
        if data:
            for item in data:
                item_str = str(item)
                list_item = ListItem(Label(item_str))
                self.item_data.append(item)
                await self.list_view.append(list_item)
        else:
            # If no data, show a message
            await self.list_view.append(ListItem(Label("No items found")))

    def toggle_disabled(self):
        """Toggle the disabled state of the widget."""
        self.is_disabled = not self.is_disabled
        # Update the disabled property of the ListView
        self.list_view.disabled = self.is_disabled
        if self.is_disabled:
            self.add_class("disabled")
            self.app.log("List disabled")
        else:
            self.remove_class("disabled")

        # Force a refresh to ensure the disabled state is applied
        self.refresh()

    def watch_is_disabled(self, is_disabled: bool):
        """React to changes in the disabled state."""
        # Update the disabled property of the ListView
        self.list_view.disabled = is_disabled
        if is_disabled:
            self.add_class("disabled")
        else:
            self.remove_class("disabled")

        # Force a refresh to ensure the disabled state is applied
        self.refresh()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Handle the highlighted event from ListView."""
        if self.is_disabled:
            return

        # Show the save message when the selection changes
        self.value_changed = True
        self.save_message.display = True
        # Force a refresh to ensure the save message is displayed
        self.save_message.refresh()

        # Post a message about the selection change
        if event.item is not None and self.list_view.index is not None and 0 <= self.list_view.index < len(self.item_data):
            selected_item = self.item_data[self.list_view.index]
            self.post_message(self.SelectionChanged(self, selected_item))

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle the selected event from ListView."""
        if self.is_disabled:
            return

        # Hide the save message
        self.save_message.display = False

        # Call the on_change callback if provided
        if self.value_changed and self.on_change and self.list_view.index is not None and 0 <= self.list_view.index < len(self.item_data):
            self.value_changed = False
            selected_item = self.item_data[self.list_view.index]
            if callable(self.on_change):
                await self.on_change(selected_item)

    @property
    def selected_item(self) -> Optional[Any]:
        """Get the currently selected item."""
        if self.list_view.index is not None and 0 <= self.list_view.index < len(self.item_data):
            return self.item_data[self.list_view.index]
        return None

    def focus(self, scroll_visible: bool = True) -> None:
        """Focus the input field."""
        self.list_view.focus()
