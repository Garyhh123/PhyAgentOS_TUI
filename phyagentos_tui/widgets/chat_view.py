"""Chat message display widget."""

from rich import box
from rich.align import Align
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import ScrollableContainer
from textual.widgets import Static


class ChatView(ScrollableContainer):
    """Scrollable chat message display."""

    def __init__(self) -> None:
        super().__init__()
        self._messages: list[tuple[str, str]] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="chat-content")

    def add_user_message(self, message: str) -> None:
        """Add a user message to the chat."""
        self._messages.append(("user", message))
        self._refresh()

    def add_agent_message(self, message: str) -> None:
        """Add an agent message to the chat."""
        self._messages.append(("agent", message))
        self._refresh()

    def add_progress(self, message: str) -> None:
        """Add a progress hint to the chat."""
        self._messages.append(("progress", message))
        self._refresh()

    def add_note(self, message: str) -> None:
        """Add a lightweight, unframed note to the chat."""
        self._messages.append(("note", message))
        self._refresh()

    def _refresh(self) -> None:
        """Render the transcript with a centered, compact message lane."""
        content = Group(*(self._render_entry(kind, message) for kind, message in self._messages))
        self.query_one("#chat-content", Static).update(content)
        self.call_after_refresh(self.scroll_end, animate=False)

    def clear_messages(self) -> None:
        """Clear all chat messages."""
        self._messages.clear()
        self.query_one("#chat-content", Static).update("")

    def on_resize(self, event) -> None:  # type: ignore[override]
        """Keep message cards centered after a terminal resize."""
        if self._messages:
            self._refresh()

    def _render_entry(self, kind: str, message: str) -> RenderableType:
        width = self._card_width()
        if kind == "user":
            title = "You"
            border = "#6b8ca8"
            body: RenderableType = Text(message)
        elif kind == "agent":
            title = "PhyAgentOS"
            border = "#5c7385"
            body = Markdown(message)
        elif kind == "progress":
            title = "Status"
            border = "#8d97a3"
            body = Text(message, style="italic #8d97a3")
        else:
            return Padding(
                Align.center(Text(message, style="italic #8d97a3")),
                (0, 0, 1, 0),
            )

        card = Panel(
            body,
            title=title,
            title_align="left",
            border_style=border,
            box=box.ROUNDED,
            padding=(0, 1),
            width=width,
            expand=False,
        )
        return Padding(Align.center(card), (0, 0, 1, 0))

    def _card_width(self) -> int:
        width = getattr(self.size, "width", 0) or 0
        if width <= 0:
            return 72
        return max(42, min(76, width - 10))

