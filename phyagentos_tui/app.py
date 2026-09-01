"""PhyAgentOS TUI Application."""

import time
from pathlib import Path

from PhyAgentOS import __logo__, __version__
from PhyAgentOS.config.loader import load_config
from PhyAgentOS.config.schema import Config
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen

from phyagentos_tui.themes import THEMES, get_theme_name
from phyagentos_tui.widgets.app_header import AppHeader
from phyagentos_tui.widgets.command_palette import CommandPalette
from phyagentos_tui.widgets.nav_bar import NavBar


class PhyAgentOSApp(App):
    """PhyAgentOS Terminal User Interface."""

    TITLE = f"{__logo__} PhyAgentOS"
    SUB_TITLE = f"v{__version__}"
    ENABLE_COMMAND_PALETTE = False

    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("escape", "back_or_quit", "Back / Quit x2", priority=True),
        Binding("ctrl+k", "toggle_command_palette", "Command", priority=True),
        Binding("alt+left", "previous_page", "Previous page", show=False),
        Binding("alt+right", "next_page", "Next page", show=False),
        Binding("ctrl+r", "restart_gateway", "Restart Gateway"),
        Binding("ctrl+1", "switch_screen('chat')", "Chat", show=False),
        Binding("ctrl+2", "switch_screen('providers')", "Providers", show=False),
        Binding("ctrl+3", "switch_screen('channels')", "Channels", show=False),
        Binding("ctrl+4", "switch_screen('settings')", "Settings", show=False),
        Binding("ctrl+5", "switch_screen('runtime')", "Runtime", show=False),
    ]

    def __init__(self, config_path: str | None = None):
        super().__init__()
        for theme in THEMES.values():
            self.register_theme(theme)
        self._config_path = config_path
        self._config: Config | None = None
        self._gateway_service = None
        self._esc_last = 0.0
        self._current_screen_name = "chat"
        self._screen_order = ("chat", "providers", "channels", "settings", "runtime")
        if config_path:
            from PhyAgentOS.config.loader import set_config_path

            set_config_path(Path(config_path).expanduser())
        self.theme = get_theme_name(self.config.tui.theme)

    @property
    def config(self) -> Config:
        if self._config is None:
            self._config = load_config(self._config_file)
        return self._config

    @property
    def _config_file(self) -> Path | None:
        return Path(self._config_path).expanduser() if self._config_path else None

    def reload_config(self) -> None:
        self._config = load_config(self._config_file)

    def compose(self) -> ComposeResult:
        # Chrome (AppHeader/Nav/Footer) is composed inside each screen, because
        # App.compose mounts onto the default screen which gets covered when
        # the chat screen is pushed.
        yield from ()

    def on_mount(self) -> None:
        self._start_gateway()
        self.switch_to_chat()

    def _start_gateway(self) -> None:
        from phyagentos_tui.services.gateway_service import GatewayService
        self._gateway_service = GatewayService(self.config, self)
        self.run_worker(self._gateway_service.start(), exclusive=False)

    async def restart_gateway(self) -> None:
        """Stop the gateway, reload config, and start it again."""
        from phyagentos_tui.services.gateway_service import GatewayService

        if self._gateway_service is not None:
            await self._gateway_service.stop()
        self.reload_config()
        self._gateway_service = GatewayService(self.config, self)
        await self._gateway_service.start()
        if self._gateway_service.error:
            self.notify(
                f"Gateway not started: {self._gateway_service.error}",
                severity="error",
                timeout=8,
            )
        else:
            self.notify("Gateway restarted")
        try:
            self.query_one(AppHeader).refresh_header()
        except Exception:
            pass
        try:
            from phyagentos_tui.widgets.status_pane import StatusPane

            self.screen.query_one(StatusPane).refresh_status()
        except Exception:
            pass

    async def action_restart_gateway(self) -> None:
        await self.restart_gateway()

    def switch_to_chat(self) -> None:
        from phyagentos_tui.screens.chat import ChatScreen
        self.push_screen(ChatScreen())

    def _active_palette(self) -> CommandPalette | None:
        try:
            return self.screen.query_one(CommandPalette)
        except Exception:
            return None

    async def action_toggle_command_palette(self) -> None:
        palette = self._active_palette()
        if palette is not None:
            await palette.toggle()

    def action_back_or_quit(self) -> None:
        """Esc: close command palette, go back from sub-screens, double-press to quit."""
        palette = self._active_palette()
        if palette is not None and palette.is_open:
            palette.close()
            self._focus_default_widget()
            return

        if self._current_screen_name == "chat":
            now = time.monotonic()
            if now - self._esc_last < 2.0:
                self._esc_last = 0.0
                self.exit()
            else:
                self._esc_last = now
                self.notify("再按一次 Esc 退出", timeout=2)
        else:
            self._esc_last = 0.0
            self.action_switch_screen("chat")

    def action_switch_screen(self, screen_name: str) -> None:
        screen_map = {
            "chat": self._get_chat_screen,
            "providers": self._get_providers_screen,
            "channels": self._get_channels_screen,
            "settings": self._get_settings_screen,
            "runtime": self._get_runtime_screen,
        }
        factory = screen_map.get(screen_name)
        if factory:
            self._current_screen_name = screen_name
            self.switch_screen(factory())

    def action_previous_page(self) -> None:
        self._switch_relative_page(-1)

    def action_next_page(self) -> None:
        self._switch_relative_page(1)

    def _switch_relative_page(self, delta: int) -> None:
        try:
            index = self._screen_order.index(self._current_screen_name)
        except ValueError:
            index = 0
        next_name = self._screen_order[(index + delta) % len(self._screen_order)]
        self.action_switch_screen(next_name)

    def on_nav_bar_selected(self, event: NavBar.Selected) -> None:
        event.stop()
        self.action_switch_screen(event.name)

    async def on_command_palette_selected(self, event: CommandPalette.Selected) -> None:
        event.stop()
        palette = self._active_palette()
        if palette is not None:
            palette.close()

        if event.name == "restart_gateway":
            await self.restart_gateway()
            self._focus_default_widget()
            return

        self.action_switch_screen(event.name)

    def _focus_default_widget(self) -> None:
        focusers = (
            "#chat-input-field",
            "#provider-table",
            "#channels-table",
            "#setting-model",
            "#runtime-sessions",
        )
        for selector in focusers:
            try:
                self.screen.query_one(selector).focus()
                return
            except Exception:
                continue

    def _get_chat_screen(self) -> Screen:
        from phyagentos_tui.screens.chat import ChatScreen
        return ChatScreen()

    def _get_providers_screen(self) -> Screen:
        from phyagentos_tui.screens.providers import ProvidersScreen
        return ProvidersScreen()

    def _get_channels_screen(self) -> Screen:
        from phyagentos_tui.screens.channels import ChannelsScreen
        return ChannelsScreen()

    def _get_settings_screen(self) -> Screen:
        from phyagentos_tui.screens.settings import SettingsScreen
        return SettingsScreen()

    def _get_runtime_screen(self) -> Screen:
        from phyagentos_tui.screens.runtime import RuntimeDashboardScreen
        return RuntimeDashboardScreen()

    async def on_unmount(self) -> None:
        if self._gateway_service is not None:
            await self._gateway_service.stop()


def run_tui(config_path: str | None = None) -> None:
    """Run the PhyAgentOS TUI."""
    app = PhyAgentOSApp(config_path=config_path)
    app.run()

