"""OptionList-related widgets for the Nautex TUI."""

from textual.widgets import Label, OptionList
from textual.containers import Vertical


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