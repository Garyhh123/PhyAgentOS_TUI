"""Slim application footer for global keyboard hints."""

from textual.widgets import Static


class AppFooter(Static):
    """Small footer that avoids Textual's built-in command palette hints."""

    DEFAULT_CSS = ""

    def __init__(self) -> None:
        super().__init__(
            "Ctrl+1..5 pages   Ctrl+K command   Alt+Left/Right switch   Esc back/quit",
            classes="app-footer",
        )

