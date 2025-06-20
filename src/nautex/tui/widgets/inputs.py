"""Input-related widgets for the Nautex TUI."""

from typing import Callable, Optional, Union, Awaitable

from textual.widgets import Input, Label, Button
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Markdown


class ValidatedTextInput(Vertical):
    """A text input with validation, check mark, and error message."""

    DEFAULT_CSS = """
    ValidatedTextInput {
        height: auto;
        margin: 0;
        padding: 0 1;
        border: solid $primary;
    }

    /* ───────────────── title ───────────────── */
    ValidatedTextInput > .title-row {
        height: 1;
        margin-left: 1;
    }

    /* ───────────────── input row ───────────────── */
    ValidatedTextInput > .input-row {
        height: auto;
    }

    ValidatedTextInput .input-field {
        width: 1fr;          /* fill remaining space */
    }

    /* status icon as a button so it is clickable / focusable */
    ValidatedTextInput .status-button {
        width: 3;
        height: 3;
        border: none;
        margin: 0 1 0 0;
        padding: 0;
        color: $text;
    }

    ValidatedTextInput .status-button-success {
        background: $success-darken-2;
    }

    ValidatedTextInput .status-button-error {
        background: $error-darken-2;
    }

    ValidatedTextInput .status-button-neutral {
        background: $surface;
    }

    /* ───────────────── footer (error + hint) ───────────────── */
    ValidatedTextInput > .footer-row {
        height: 1;           /* single terminal row */
        margin-top: 0;
    }

    ValidatedTextInput .error-row {
        width: 1fr;          /* stretch; pushes hint to the right */
        color: $error;
        margin-left: 1;
    }

    ValidatedTextInput .save-message {
        width: auto;
        align-horizontal: right;
        color: $text-muted;
        display: none;       /* shown only when value changes */
        margin-right: 1;
    }
    """

    def __init__(
        self, 
        title: str, 
        placeholder: str = "", 
        validator: Optional[Callable[[str], Awaitable[tuple[bool, str]]]] = None,
        title_extra: Optional[Union[Static, Markdown]] = None,
        default_value: str = "",
        on_change: Optional[Callable[[str], Awaitable[None]]] = None,
        validate_on_init: bool = False,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.border_title = title
        self.placeholder = placeholder
        self.validator = validator
        self.title_extra = title_extra
        self.default_value = default_value
        self.on_change = on_change
        self.validate_on_init = validate_on_init

        # Create widgets
        self.input_field = Input(placeholder=placeholder, value=default_value, classes="input-field")

        # Create a button for the status icon
        self.status_button = Button(" ", classes="status-button status-button-neutral")

        self.status_button.styles.max_width = 7

        # Add a message for when value changes
        self.save_message = Static("press enter to save", classes="save-message")
        self.save_message.display = False

        self.error_text = Static("", classes="error-row")

        # Track validation state
        self.is_valid = True
        self.error_message = ""
        self.value_changed = False
        self.validation_occurred = False

    def compose(self):
        """Compose the validated input layout."""
        with Horizontal(classes="title-row"):
            if self.title_extra:
                yield self.title_extra

        with Horizontal(classes="input-row"):
            yield self.input_field
            yield self.status_button

        with Horizontal(classes="footer-row"):
            yield self.error_text  # left
            yield self.save_message  # right

    def on_mount(self):
        """Called when the widget is mounted."""
        # Validate the initial value when the widget is mounted (if validate_on_init is True)
        if self.validator and self.validate_on_init:
            self.app.call_later(self.validate_initial)
        # If no validator or not validating on init, ensure we stay in neutral state
        else:
            self.status_button.label = " "
            self.status_button.add_class("status-button-neutral")
            self.status_button.remove_class("status-button-success")
            self.status_button.remove_class("status-button-error")

    async def validate_initial(self):
        """Validate the initial value."""
        if self.validator:
            await self.validate()

    def on_input_changed(self, event):
        """Handle input value changes."""
        # Show the save message when the value changes
        self.value_changed = True
        self.save_message.display = True

        # No validation here - validation happens only on Enter key press

    async def on_input_submitted(self, event):
        """Handle input submission (Enter key)."""
        # Always hide the save message when Enter is pressed
        self.save_message.display = False

        # Validate the input when Enter is pressed
        self.set_status("wait")

        if self.validator:
            valid = await self.validate()
        else:
            valid = True

        self.set_status("valid" if valid else "invalid")

        # Only call on_change if the value has changed and validation passed
        if self.value_changed and self.on_change and valid:
            self.value_changed = False
            # Call the on_change callback
            await self.on_change(self.value)


    def set_status(self, status: str):
        if status == "valid":
            self.status_button.label = "✓"
            self.status_button.remove_class("status-button-error")
            self.status_button.remove_class("status-button-neutral")
            self.status_button.add_class("status-button-success")
            self.error_text.update("")
        elif status == "wait":
            self.status_button.label = "⌛"
            self.status_button.remove_class("status-button-error")
            self.status_button.remove_class("status-button-success")

            self.status_button.add_class("status-button-neutral")
            self.error_text.update("")
        elif status == "invalid":
            self.status_button.label = "✗"
            self.status_button.remove_class("status-button-success")
            self.status_button.remove_class("status-button-neutral")
            self.status_button.add_class("status-button-error")
            self.error_text.update(self.error_message)
        else:
            self.status_button.label = ""
            self.status_button.remove_class("status-button-success")
            self.status_button.remove_class("status-button-error")
            self.status_button.add_class("status-button-neutral")
            self.error_text.update("")


    async def validate(self) -> bool:
        """Validate the current input value."""
        if self.validator:
            self.is_valid, self.error_message = await self.validator(self.value)
            self.validation_occurred = True

            # Remove neutral state if this is the first validation
            self.status_button.remove_class("status-button-neutral")

        return self.is_valid

    @property
    def value(self) -> str:
        """Get the input value."""
        return self.input_field.value

    def set_value(self, value: str) -> None:
        """Set the input value."""
        self.input_field.value = value

        # Reset the value_changed flag and hide the save message
        self.value_changed = False
        self.save_message.display = False

        # Reset to neutral state unless we've already validated
        if not self.validation_occurred:
            self.status_button.label = " "
            self.status_button.remove_class("status-button-success")
            self.status_button.remove_class("status-button-error")
            self.status_button.add_class("status-button-neutral")

        # Only validate if validate_on_init is True
        if self.validator and self.validate_on_init:
            self.app.call_later(self.validate)

    def focus(self, scroll_visible: bool = True) -> None:
        """Focus the input field."""
        self.input_field.focus()
