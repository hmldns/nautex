"""Loadable list widget for the Nautex TUI."""

import asyncio
import inspect
from typing import Callable, List, Optional, Any, Union, Awaitable, Iterable, Tuple

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
        width: 100%;
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

    /* Taller item to show animated LoadingIndicator clearly */
    LoadableList .loading-item {
        height: 3;
        align: center middle;  /* centers children both ways */
        background: $surface-lighten-1;
    }

    /* Style the spinner for visibility */
    LoadableList .loading-item > LoadingIndicator {
        color: $primary;
    }

    /* Add vertical breathing room between border and first/last item */
    LoadableList .list-view {
        padding-top: 1;
        padding-bottom: 1;
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
        data_loader: Optional[Callable[[], Awaitable[Tuple[List, Optional[int]]]]] = None,
        on_change: Optional[Callable[[Any], Awaitable[None]]] = None,
        **kwargs
    ):
        """Initialize the LoadableList widget.

        Args:
            title: The title of the list widget
            data_loader: A callable that returns data to be displayed in the list (can be async).
                         Can return either a list of items or a tuple of (items_list, selected_index)
                         where selected_index is the index of the item to be selected after loading.
            on_change: Async callback function called when the selection changes and Enter is pressed
        """
        super().__init__(**kwargs)
        self.border_title = title
        self.data_loader = data_loader
        self.on_change = on_change
        self.empty_message = "No items found"

        # Create widgets
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
        """Called when the widget is mounted.

        This method schedules the load_data method to be called in the next event loop iteration.
        It works with both synchronous and asynchronous data loaders.
        """
        # Load initial data
        self.app.call_later(self.load_data)

    def reload(self):
        """Reload the list data.

        This method schedules the load_data method to be called in the next event loop iteration.
        It works with both synchronous and asynchronous data loaders.
        """
        # Set loading state immediately to provide visual feedback
        self.is_loading = True
        # Schedule the load_data method to be called in the next event loop iteration
        self.app.call_later(self.load_data)

    async def load_data(self):
        """Load data into the list.

        If the data_loader returns a tuple of (items_list, selected_index),
        the selected_index will be used to set the selected item after loading.
        Otherwise, it expects the data_loader to return just a list of items.
        """
        # Show loading state
        self.is_loading = True

        # Clear existing items
        await self.list_view.clear()

        # Create loading indicator dynamically to avoid re-mounting issues
        loading_spinner = LoadingIndicator()
        loading_item = ListItem(loading_spinner, classes="loading-item")
        await self.list_view.append(loading_item)

        # Disable interaction while loading
        self.list_view.disabled = True

        # Check if the list is disabled
        if self.is_disabled:
            # If disabled, show a message and don't load data
            self.is_loading = False
            await self.list_view.clear()
            await self.list_view.append(ListItem(Label("List is disabled")))
            return

        # Load data
        if self.data_loader:
            try:
                # Check if the data_loader is a coroutine function
                if inspect.iscoroutinefunction(self.data_loader):
                    # If it's async, await it
                    result = await self.data_loader()
                else:
                    # If it's not async, call it directly
                    result = self.data_loader()
            except Exception as e:
                self.app.log(f"Error loading data: {str(e)}")
                result = ["Error loading data"]
        else:
            # No data loader provided
            result = []

        # Update UI with data
        self.is_loading = False

        # Clear previous items (loading indicator)
        await self.list_view.clear()

        # Check if result is a tuple with (items_list, selected_index)
        selected_index = None
        if isinstance(result, tuple) and len(result) == 2:
            data, selected_index = result
        else:
            data = result

        # Add items to the list
        self.item_data = []
        if data:
            for item in data:
                # Use name attribute if available, otherwise convert to string
                item_str = item.name if hasattr(item, 'name') else str(item)
                list_item = ListItem(Label(item_str))
                self.item_data.append(item)
                await self.list_view.append(list_item)

            # Set selected item if provided
            if selected_index is not None and 0 <= selected_index < len(self.item_data):
                self.list_view.index = selected_index
        else:
            # If no data, show the empty message
            items = self.empty_message.split("\n")
            list_items = [ListItem(Label(l)) for l in items]
            await self.list_view.extend(list_items)

        # Re-enable interaction
        self.list_view.disabled = self.is_disabled  # remain disabled only if explicitly disabled

    def toggle_disabled(self):
        """Toggle the disabled state of the widget."""
        # Deprecated in favour of explicit enable/disable helpers
        if self.is_disabled:
            self.enable()
        else:
            self.disable()

    # ---------------------------------------------------------------------
    # New explicit helpers for clarity when controlling the list externally
    # ---------------------------------------------------------------------

    def disable(self):
        """Disable interaction with the list and apply disabled styles."""
        self.is_disabled = True
        self.list_view.disabled = True
        self.add_class("disabled")
        self.app.log("List disabled")
        self.refresh()

    def enable(self):
        """Enable interaction with the list and remove disabled styles."""
        self.is_disabled = False
        self.list_view.disabled = False
        self.remove_class("disabled")
        self.app.log("List enabled")
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

    def set_empty_message(self, message: str) -> None:
        """Set the message to display when the list is empty.

        Args:
            message: The message to display
        """
        self.empty_message = message
