"""Persistent page navigation for the TUI."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Static

NAV_ITEMS = (
    ("chat", "Chat"),
    ("providers", "Providers"),
    ("channels", "Channels"),
    ("settings", "Settings"),
    ("runtime", "Forge"),
)


class NavItem(Static):
    """Focusable text item for top-level navigation."""

    can_focus = True

    BINDINGS = [
        Binding("enter", "select", show=False),
        Binding("space", "select", show=False),
    ]

    def __init__(self, name: str, label: str, active: bool) -> None:
        classes = "nav-item active" if active else "nav-item"
        super().__init__(label, id=f"nav-{name}", classes=classes)
        self.nav_name = name

    def action_select(self) -> None:
        self.post_message(NavBar.Selected(self.nav_name))

    def on_click(self) -> None:
        self.action_select()


class NavBar(Horizontal):
    """Always-visible navigation strip."""

    class Selected(Message):
        """Emitted when a nav item is chosen."""

        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name

    def __init__(self, active: str) -> None:
        super().__init__()
        self.active = active

    def compose(self) -> ComposeResult:
        for name, label in NAV_ITEMS:
            yield NavItem(name, label, name == self.active)
        yield Static("Command  Ctrl+K", classes="nav-command-hint")

