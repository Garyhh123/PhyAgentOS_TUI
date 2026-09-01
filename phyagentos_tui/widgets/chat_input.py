"""Chat input widget."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Input, Static


class ChatInput(Vertical):
    """Chat input with an action bar and submit row."""

    class Submitted(Message):
        """Emitted when user submits a message."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class CommandRequested(Message):
        """Emitted when the command button is pressed."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="chat-input-toolbar"):
            yield Static("Action center", classes="chat-input-title")
            yield Static("cli:direct", classes="chat-input-badge")
            yield Button("Cmd", id="chat-cmd-btn")
            yield Button("Clear", id="chat-clear-btn")
        with Horizontal(id="chat-input-row"):
            yield Input(placeholder="Type your message... (Enter to send)", id="chat-input-field")
            yield Button("Send", variant="primary", id="chat-send-btn")
        yield Static("Enter sends  •  Ctrl+K opens command  •  Esc goes back", classes="chat-input-hint")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key."""
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle send button click."""
        if event.button.id == "chat-send-btn":
            self._submit()
        elif event.button.id == "chat-clear-btn":
            self.clear_input()
        elif event.button.id == "chat-cmd-btn":
            self.post_message(self.CommandRequested())

    def _submit(self) -> None:
        """Submit the current input."""
        input_field = self.query_one("#chat-input-field", Input)
        text = input_field.value.strip()
        if text:
            self.post_message(self.Submitted(text))
            input_field.value = ""

    def clear_input(self) -> None:
        """Clear the current input field."""
        input_field = self.query_one("#chat-input-field", Input)
        input_field.value = ""
        input_field.focus()

    def focus_input(self) -> None:
        """Focus the input field."""
        input_field = self.query_one("#chat-input-field", Input)
        input_field.focus()

