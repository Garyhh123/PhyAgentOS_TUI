"""Style lab v2: structurally different UI directions (not recolors).

Run:  python -m PhyAgentOS.tui.style_lab
Keys: 1-5 switch layout, q quit, Tab toggles menu in layout 3.
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Middle, Vertical
from textual.screen import Screen
from textual.theme import Theme
from textual.widgets import DataTable, Label, ListItem, ListView, Static

from PhyAgentOS.tui.widgets.pixel_font import render_pixel_text

CHAT_MOCK = (
    "You: 帮我查一下明天的天气\n\n"
    "PhyAgentOS: 好的，我来调用搜索工具查询…\n"
    "  ↳ web_search(明天天气)\n\n"
    "PhyAgentOS: 明天晴，18–26°C，适合出行。"
)

NAV = ["Chat", "Providers", "Channels", "Settings", "Status", "Logs"]

THEMES = {
    "dark": Theme(
        name="dark", primary="#ffb454", secondary="#3a3f55", accent="#7fd4c1",
        foreground="#d8d5c5", background="#14161e", surface="#1a1c26",
        panel="#20222e", boost="#2a2d3a", warning="#e0af68", error="#f7768e", dark=True,
    ),
    "blue": Theme(
        name="blue", primary="#7aa2f7", secondary="#414868", accent="#73daca",
        foreground="#c0caf5", background="#1e2030", surface="#24283b",
        panel="#2b2f40", boost="#343a52", warning="#e0af68", error="#f7768e", dark=True,
    ),
}


def _mock_table() -> DataTable:
    table = DataTable()
    table.add_columns("Provider", "Status")
    table.add_row("Anthropic", "not set")
    table.add_row("DeepSeek", "configured")
    return table


# ---------------------------------------------------------------------------
# 1. Sidebar (当前基线：左侧导航 + 内容)
# ---------------------------------------------------------------------------
class SidebarScreen(Screen):
    def compose(self) -> ComposeResult:
        with Vertical(id="side"):
            yield Static(render_pixel_text("PAOS"), classes="logo")
            yield ListView(*[ListItem(Label(n)) for n in NAV], id="nav")
        with Vertical(id="main"):
            yield Static("░▒▓ CHAT ▓▒░", classes="strip")
            yield Static(CHAT_MOCK, id="chat", classes="panel")
            yield Static("▊ Type your message...", classes="fake-input")


# ---------------------------------------------------------------------------
# 2. TopTabs (顶部标签栏，无侧栏)
# ---------------------------------------------------------------------------
class TopTabsScreen(Screen):
    def compose(self) -> ComposeResult:
        with Horizontal(id="tabs"):
            for i, n in enumerate(NAV):
                yield Label(f" {n} ", classes="tab" + (" active" if i == 0 else ""))
        yield Static(CHAT_MOCK, id="chat", classes="panel")
        with Horizontal(id="input-row"):
            yield Static("▊ Type your message... (1-5 切换布局)", classes="fake-input")
            yield Static(" Send ", classes="fake-button")


# ---------------------------------------------------------------------------
# 3. FullChat (沉浸对话，菜单用浮层)
# ---------------------------------------------------------------------------
class FullChatScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Static(CHAT_MOCK, id="chat")
        yield Static("▊ Type your message... (Tab 打开菜单)", classes="fake-input")
        with Center(id="menu-overlay"):
            with Vertical(id="menu-box"):
                yield Static("░▒▓ MENU ▓▒░", classes="strip")
                yield ListView(*[ListItem(Label(n)) for n in NAV], id="menu-list")

    def on_mount(self) -> None:
        self.query_one("#menu-overlay").display = False

    def action_toggle_menu(self) -> None:
        overlay = self.query_one("#menu-overlay")
        overlay.display = not overlay.display
        if overlay.display:
            self.query_one("#menu-list", ListView).focus()


# ---------------------------------------------------------------------------
# 4. Tiling (平铺仪表盘：聊天 + 常驻状态/日志栏)
# ---------------------------------------------------------------------------
class TilingScreen(Screen):
    def compose(self) -> ComposeResult:
        with Horizontal(id="tile-main"):
            with Vertical(id="tile-left"):
                yield Static(CHAT_MOCK, id="chat", classes="panel")
                yield Static("▊ Type your message...", classes="fake-input")
            with Vertical(id="tile-right"):
                yield Static("░▒▓ STATUS ▓▒░", classes="strip")
                yield Static(
                    "Model: claude-opus-4-5\nGateway: running\nChannels: 0 enabled",
                    id="status-pane",
                    classes="panel",
                )
                yield Static("░▒▓ LOGS ▓▒░", classes="strip")
                yield Static(
                    "[13:01] agent loop started\n[13:01] cron started\n[13:02] message processed",
                    id="logs-pane",
                    classes="panel",
                )


# ---------------------------------------------------------------------------
# 5. GameMenu (游戏主菜单：居中大 logo + 居中菜单)
# ---------------------------------------------------------------------------
class GameMenuScreen(Screen):
    def compose(self) -> ComposeResult:
        with Middle():
            with Center():
                with Vertical(id="game-menu"):
                    yield Static(render_pixel_text("PAOS"), classes="big-logo")
                    yield Static("░▒▓█▓▒░░▒▓█▓▒░", classes="dither")
                    yield ListView(*[ListItem(Label(n)) for n in NAV], id="game-nav")
                    yield Static("↑↓ 选择 · Enter 进入 · Esc 退出", classes="hint")


SCREENS = {
    "1": ("sidebar", "dark"),
    "2": ("tabs", "blue"),
    "3": ("fullchat", "dark"),
    "4": ("tiling", "blue"),
    "5": ("gamemenu", "dark"),
}


class StyleLab(App):
    """Structurally different UI directions."""

    CSS_PATH = "style_lab.tcss"

    MODES = {
        "sidebar": SidebarScreen,
        "tabs": TopTabsScreen,
        "fullchat": FullChatScreen,
        "tiling": TilingScreen,
        "gamemenu": GameMenuScreen,
    }

    DEFAULT_MODE = "sidebar"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("1", "go('1')", "Sidebar"),
        Binding("2", "go('2')", "TopTabs"),
        Binding("3", "go('3')", "FullChat"),
        Binding("4", "go('4')", "Tiling"),
        Binding("5", "go('5')", "GameMenu"),
    ]

    def __init__(self) -> None:
        super().__init__()
        for theme in THEMES.values():
            self.register_theme(theme)
        self.theme = "dark"

    def action_go(self, key: str) -> None:
        mode, theme = SCREENS[key]
        self.theme = theme
        self.switch_mode(mode)

    def on_key(self, event) -> None:
        if event.key == "tab" and isinstance(self.screen, FullChatScreen):
            self.screen.action_toggle_menu()
            event.prevent_default()


if __name__ == "__main__":
    StyleLab().run()
