"""Command palette overlay for quick navigation and actions."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.message import Message
from textual.widgets import Input, Label, ListItem, ListView, Static

COMMANDS = (
    ("chat", "Open Chat", "Ctrl+1"),
    ("providers", "Open Providers", "Ctrl+2"),
    ("channels", "Open Channels", "Ctrl+3"),
    ("settings", "Open Settings", "Ctrl+4"),
    ("runtime", "Open Forge Runtime", "Ctrl+5"),
    ("restart_gateway", "Restart Gateway", "Ctrl+R"),
)


class CommandListView(ListView):
    """ListView with common navigation aliases."""

    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("right", "select_cursor", show=False),
    ]


class CommandPalette(Center):
    """A small searchable command launcher toggled with Ctrl+K."""

    class Selected(Message):
        """Emitted when a command is chosen."""

        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name

    def __init__(self) -> None:
        super().__init__()
        self._query = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="command-palette-box"):
            yield Static("Command", classes="command-palette-title")
            yield Input(placeholder="Search pages and actions...", id="command-palette-input")
            yield CommandListView(id="command-palette-list")

    async def on_mount(self) -> None:
        self.display = False
        await self._refresh_items()

    async def open(self) -> None:
        self.display = True
        input_field = self.query_one("#command-palette-input", Input)
        input_field.value = ""
        self._query = ""
        await self._refresh_items()
        input_field.focus()

    def close(self) -> None:
        self.display = False

    async def toggle(self) -> None:
        if self.display:
            self.close()
        else:
            await self.open()

    @property
    def is_open(self) -> bool:
        return bool(self.display)

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "command-palette-input":
            return
        self._query = event.value.strip().lower()
        await self._refresh_items()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "command-palette-input":
            return
        list_view = self.query_one("#command-palette-list", CommandListView)
        if list_view.index is None and len(list_view.children) > 0:
            list_view.index = 0
        list_view.action_select_cursor()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        if not item_id.startswith("command-"):
            return
        self.post_message(self.Selected(item_id[8:]))

    async def _refresh_items(self) -> None:
        list_view = self.query_one("#command-palette-list", CommandListView)
        await list_view.clear()
        for name, label, shortcut in self._filtered_commands():
            row = Horizontal(
                Label(label, classes="command-label"),
                Static(shortcut, classes="command-shortcut"),
            )
            await list_view.append(ListItem(row, id=f"command-{name}"))
        if len(list_view.children) > 0:
            list_view.index = 0

    def _filtered_commands(self) -> list[tuple[str, str, str]]:
        if not self._query:
            return list(COMMANDS)
        return [
            command
            for command in COMMANDS
            if self._query in " ".join(command).lower()
        ]

