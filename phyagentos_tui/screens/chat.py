"""Chat screen for PhyAgentOS TUI."""

import asyncio

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen

from PhyAgentOS.bus.events import InboundMessage
from phyagentos_tui.widgets.app_footer import AppFooter
from phyagentos_tui.widgets.app_header import AppHeader
from phyagentos_tui.widgets.chat_input import ChatInput
from phyagentos_tui.widgets.chat_view import ChatView
from phyagentos_tui.widgets.command_palette import CommandPalette
from phyagentos_tui.widgets.log_view import LogView
from phyagentos_tui.widgets.nav_bar import NavBar
from phyagentos_tui.widgets.section_title import SectionTitle
from phyagentos_tui.widgets.status_pane import StatusPane


class ChatScreen(Screen):
    """Main screen: chat (2fr) + status/logs column (1fr)."""

    def __init__(self) -> None:
        super().__init__()
        self._outbound_task: asyncio.Task | None = None
        self._sink_id: int | None = None

    def compose(self) -> ComposeResult:
        yield AppHeader()
        yield NavBar("chat")
        with Horizontal(id="tile-main"):
            with Vertical(id="tile-left"):
                yield SectionTitle("Chat · cli:direct")
                yield ChatView()
                yield ChatInput()
            with Vertical(id="tile-right"):
                yield SectionTitle("Status")
                yield StatusPane()
                yield SectionTitle("Logs")
                yield LogView()
        yield CommandPalette()
        yield AppFooter()

    def on_mount(self) -> None:
        """Start outbound consumer and log capture."""
        self._setup_loguru_capture()

        gateway = getattr(self.app, "_gateway_service", None)
        chat_view = self.query_one(ChatView)

        if gateway is None:
            chat_view.add_progress("Gateway service not initialized.")
        elif gateway.error:
            chat_view.add_progress(f"Gateway not started: {gateway.error}")
            chat_view.add_progress("Open Ctrl+K command -> Providers to configure an API key.")
        elif not gateway.is_running:
            chat_view.add_progress("Gateway starting...")

        self._outbound_task = asyncio.create_task(self._consume_outbound())
        self.query_one(ChatInput).focus_input()

    async def on_unmount(self) -> None:
        """Stop consumer and log capture."""
        if self._outbound_task:
            self._outbound_task.cancel()
            await asyncio.gather(self._outbound_task, return_exceptions=True)
        if self._sink_id is not None:
            from loguru import logger

            try:
                logger.remove(self._sink_id)
            except ValueError:
                pass
            self._sink_id = None

    def _setup_loguru_capture(self) -> None:
        """Capture loguru output into the logs pane."""
        if self._sink_id is not None:
            return
        from loguru import logger

        log_view = self.query_one(LogView)

        def tui_sink(message):
            if not log_view.is_attached:
                return
            level = message.record["level"].name
            try:
                log_view.add_log(message.record["message"], level)
            except Exception:
                pass

        self._sink_id = logger.add(tui_sink, level="DEBUG", format="{message}")

    async def _consume_outbound(self) -> None:
        """Consume outbound messages from the bus."""
        chat_view = self.query_one(ChatView)

        while True:
            gateway = getattr(self.app, "_gateway_service", None)
            bus = gateway.bus if gateway else None
            if bus is None:
                await asyncio.sleep(0.5)
                continue
            try:
                msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                if msg.metadata.get("_progress"):
                    chat_view.add_progress(msg.content)
                elif msg.content:
                    chat_view.add_agent_message(msg.content)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Handle user message submission."""
        text = event.text.strip()
        if not text:
            return

        chat_view = self.query_one(ChatView)
        chat_view.add_user_message(text)

        app = self.app
        gateway = getattr(app, "_gateway_service", None)
        if gateway is None or gateway.bus is None:
            chat_view.add_progress("Gateway not initialized.")
            return
        if gateway.error:
            chat_view.add_progress(f"Cannot send: {gateway.error}")
            chat_view.add_progress("Open Ctrl+K command -> Providers to configure an API key.")
            return
        if not gateway.is_running:
            chat_view.add_progress("Gateway starting, please wait...")
            return

        asyncio.create_task(
            gateway.bus.publish_inbound(
                InboundMessage(
                    channel="cli",
                    sender_id="user",
                    chat_id="direct",
                    content=text,
                )
            )
        )

    async def on_chat_input_command_requested(self, event: ChatInput.CommandRequested) -> None:
        """Open the command palette from the chat input controls."""
        event.stop()
        await self.app.action_toggle_command_palette()
