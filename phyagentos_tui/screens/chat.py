"""Chat screen for PhyAgentOS TUI."""

import asyncio
from collections.abc import Awaitable, Callable

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen

from PhyAgentOS.bus.events import InboundMessage
from phyagentos_tui.widgets.app_header import AppHeader
from phyagentos_tui.widgets.app_footer import AppFooter
from phyagentos_tui.widgets.chat_input import ChatInput
from phyagentos_tui.widgets.chat_view import ChatView
from phyagentos_tui.widgets.command_palette import CommandPalette
from phyagentos_tui.widgets.log_view import LogView
from phyagentos_tui.widgets.nav_bar import NavBar
from phyagentos_tui.widgets.section_title import SectionTitle
from phyagentos_tui.widgets.status_pane import StatusPane


DEMO_PROGRESS_DELAYS_S = (1.0, 1.4, 1.8, 2.3, 1.6, 2.7, 2.1, 3.2)
DEMO_FINAL_DELAY_S = 3.0


class ChatScreen(Screen):
    """Main screen: chat (2fr) + status/logs column (1fr)."""

    def __init__(self) -> None:
        super().__init__()
        self._outbound_task: asyncio.Task | None = None
        self._demo_task: asyncio.Task | None = None
        self._demo_label: str | None = None
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
        if self._demo_task and not self._demo_task.done():
            self._demo_task.cancel()
            await asyncio.gather(self._demo_task, return_exceptions=True)
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
        """Consume outbound messages from the bus. Re-fetches the bus each
        iteration so it keeps working after a gateway restart."""
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
        is_demo_launch = (
            self._is_demo01_request(text)
            or self._is_demo02_request(text)
            or self._is_demo03_request(text)
            or self._is_demo04_request(text)
        )
        if not is_demo_launch or not self._is_hidden_demo_command(text):
            chat_view.add_user_message(text)

        if self._is_demo_stop(text):
            if self._demo_task and not self._demo_task.done():
                self._demo_task.cancel()
                chat_view.add_progress(f"{self._demo_label or 'Demo'} stop requested.")
            else:
                chat_view.add_progress("No demo task is currently running.")
            return

        if self._is_demo01_request(text):
            self._start_demo01()
            return
        if self._is_demo02_request(text):
            self._start_demo02()
            return
        if self._is_demo03_request(text):
            self._start_demo03()
            return
        if self._is_demo04_request(text):
            self._start_demo04()
            return

        # Check gateway status
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

        bus = gateway.bus
        asyncio.create_task(
            bus.publish_inbound(
                InboundMessage(
                    channel="cli",
                    sender_id="user",
                    chat_id="direct",
                    content=text,
                )
            )
        )

    def _start_demo01(self) -> None:
        self._start_demo(
            "Demo 01",
            "收到 AgentTask：TCP 沿 +Z 抬高 3 cm，并把夹爪打开到 5 cm。"
            "系统会通过 Forge 发现能力、执行动作、采集 before/after evidence，并由 Verifier 关闭结果。",
            self._run_demo01,
        )

    def _start_demo02(self) -> None:
        self._start_demo(
            "Demo 02",
            "收到抓取任务：先执行初始方案，再让 Verifier 检查动作后证据；"
            "如果物体没有被保持，系统会沿同一条任务血统进入 recovery child session。",
            self._run_demo02,
        )

    def _start_demo03(self) -> None:
        self._start_demo(
            "Demo 03",
            "收到 Skill Runtime 装配任务：系统会先构建并校验 bundle，安装锁定节点制品，"
            "启动 runtime，确认工具就绪，并把运行记录封存到 Runtime。",
            self._run_demo03,
        )

    def _start_demo04(self) -> None:
        self._start_demo(
            "Demo 04",
            "收到经验演化任务：系统会先点亮阈值与边界，再慢慢回放成功如何晋升 SkillCandidate、"
            "同类失败如何激活 Scoped Lesson，以及护栏如何保留诊断边界。",
            self._run_demo04,
        )

    def _start_demo(self, label: str, message: str, runner: Callable[[], Awaitable[None]]) -> None:
        chat_view = self.query_one(ChatView)
        if self._demo_task is not None and not self._demo_task.done():
            chat_view.add_progress(f"{self._demo_label or 'A demo'} is already running.")
            return
        self._demo_label = label
        chat_view.add_agent_message(message)
        self._demo_task = asyncio.create_task(runner(), name=f"chat-{label.lower().replace(' ', '-')}-run")

    async def _run_demo01(self) -> None:
        from phyagentos_tui.demo01_runner import Demo01Runner

        await self._run_demo_events("Demo 01", Demo01Runner(self.app.config.workspace_path))

    async def _run_demo02(self) -> None:
        from phyagentos_tui.demo02_runner import Demo02Runner

        await self._run_demo_events("Demo 02", Demo02Runner(self.app.config.workspace_path))

    async def _run_demo03(self) -> None:
        from phyagentos_tui.demo03_runner import Demo03Runner

        await self._run_demo_events("Demo 03", Demo03Runner(self.app.config.workspace_path))

    async def _run_demo04(self) -> None:
        from phyagentos_tui.demo04_runner import Demo04Runner

        await self._run_demo_events("Demo 04", Demo04Runner(self.app.config.workspace_path))

    async def _run_demo_events(self, label: str, runner) -> None:
        chat_view = self.query_one(ChatView)
        log_view = self.query_one(LogView)
        displayed_stage_events: set[tuple[int, str, str]] = set()
        progress_index = 0
        total_stages = 7
        progress_delays = tuple(getattr(runner, "progress_delays_s", DEMO_PROGRESS_DELAYS_S))
        final_delay = float(getattr(runner, "final_delay_s", DEMO_FINAL_DELAY_S))

        async def add_timed_progress(
            message: str,
            *,
            level: str = "RUN",
            delay_s: float | None = None,
        ) -> None:
            nonlocal progress_index
            if delay_s is None:
                delays = progress_delays or DEMO_PROGRESS_DELAYS_S
                delay_s = delays[progress_index % len(delays)]
                progress_index += 1
            await asyncio.sleep(delay_s)
            log_view.add_log(message, level)
            chat_view.add_progress(message)

        async def handle_event(event: dict) -> None:
            nonlocal total_stages
            kind = event.get("kind")
            self._apply_demo_dashboard(label, event)
            if kind == "reset":
                stages = event.get("stages")
                if isinstance(stages, list) and stages:
                    total_stages = len(stages)
                log_view.add_log(str(event.get("title", label)), "INFO")
                await add_timed_progress(
                    str(event.get("description", f"{label} started.")),
                    level="INFO",
                )
                return
            if kind == "stage":
                stage = int(event.get("stage", 0)) + 1
                status = str(event.get("status", "running"))
                message = str(event.get("message", ""))
                key = (stage, status, message)
                if key in displayed_stage_events:
                    return
                displayed_stage_events.add(key)
                text = f"{stage}/{total_stages} [{status}] {message}"
                level = "INFO" if status == "success" else "ERROR" if status == "error" else "RUN"
                await add_timed_progress(text, level=level)
                return
            if kind == "status":
                level = str(event.get("level", "DEBUG"))
                log_view.add_log(str(event.get("message", "")), level)
                return
            if kind == "audit":
                level = str(event.get("level", "TRACE"))
                log_view.add_log(str(event.get("message", "")), level)
                return
            if kind == "done":
                await asyncio.sleep(final_delay)
                chat_view.add_note("收尾已完成，状态已记录。")
                return

        try:
            await runner.run(handle_event)
        except asyncio.CancelledError:
            await runner.stop()
            chat_view.add_progress(f"{label} stopped.")
            try:
                self.query_one(StatusPane).clear_demo_status()
            except Exception:
                pass
            raise
        except Exception as exc:
            chat_view.add_progress(f"{label} failed: {type(exc).__name__}: {exc}")
        finally:
            self._demo_task = None
            self._demo_label = None

    def _apply_demo_dashboard(self, label: str, event: dict) -> None:
        dashboard = event.get("dashboard")
        if not isinstance(dashboard, dict):
            return
        rows: dict[str, str] = {}
        for key, value in dashboard.items():
            if isinstance(value, (str, int, float, bool)):
                rows[str(key)] = str(value)
        if not rows:
            return
        try:
            self.query_one(StatusPane).show_demo_status(f"{label} Live", rows)
        except Exception:
            pass

    @staticmethod
    def _is_demo01_request(text: str) -> bool:
        normalized = text.strip().lower()
        natural_demo01 = (
            ("机械臂末端" in normalized or "tcp" in normalized)
            and ("z 轴" in normalized or "z轴" in normalized or "+z" in normalized)
            and ("3 厘米" in normalized or "3cm" in normalized or "0.03" in normalized)
            and ("夹爪" in normalized or "gripper" in normalized)
            and ("5 厘米" in normalized or "5cm" in normalized or "0.05" in normalized)
            and ("可核验" in normalized or "验证" in normalized or "证据" in normalized)
        )
        if natural_demo01:
            return True
        return normalized in {
            "demo01",
            "/demo01",
            "run demo01",
            "start demo01",
            "运行 demo01",
            "启动 demo01",
            "演示 demo01",
            "跑 demo01",
        }

    @staticmethod
    def _is_demo02_request(text: str) -> bool:
        normalized = text.strip().lower()
        natural_demo02 = (
            "杯子" in normalized
            and ("抓起来" in normalized or "抓起" in normalized)
            and ("桌面" in normalized or "桌子" in normalized)
        )
        if natural_demo02:
            return True
        return normalized in {
            "demo02",
            "/demo02",
            "run demo02",
            "start demo02",
            "运行 demo02",
            "启动 demo02",
            "演示 demo02",
            "跑 demo02",
        }

    @staticmethod
    def _is_demo03_request(text: str) -> bool:
        normalized = text.strip().lower()
        natural_demo03 = (
            "skill runtime" in normalized
            or "运行时" in normalized
            or "bundle" in normalized
            or "工具就绪" in normalized
            or "节点制品" in normalized
        )
        if natural_demo03:
            return True
        return normalized in {
            "demo03",
            "/demo03",
            "run demo03",
            "start demo03",
            "运行 demo03",
            "启动 demo03",
            "演示 demo03",
            "跑 demo03",
        }

    @staticmethod
    def _is_demo04_request(text: str) -> bool:
        normalized = text.strip().lower()
        natural_demo04 = (
            "经验" in normalized
            or "skillcandidate" in normalized
            or "scoped lesson" in normalized
            or "阈值" in normalized
            or "护栏" in normalized
        )
        if natural_demo04:
            return True
        return normalized in {
            "demo04",
            "/demo04",
            "run demo04",
            "start demo04",
            "运行 demo04",
            "启动 demo04",
            "演示 demo04",
            "跑 demo04",
        }

    @staticmethod
    def _is_hidden_demo_command(text: str) -> bool:
        normalized = text.strip().lower()
        return normalized in {
            "demo01",
            "/demo01",
            "run demo01",
            "start demo01",
            "运行 demo01",
            "启动 demo01",
            "演示 demo01",
            "跑 demo01",
            "demo02",
            "/demo02",
            "run demo02",
            "start demo02",
            "运行 demo02",
            "启动 demo02",
            "演示 demo02",
            "跑 demo02",
            "demo03",
            "/demo03",
            "run demo03",
            "start demo03",
            "运行 demo03",
            "启动 demo03",
            "演示 demo03",
            "跑 demo03",
            "demo04",
            "/demo04",
            "run demo04",
            "start demo04",
            "运行 demo04",
            "启动 demo04",
            "演示 demo04",
            "跑 demo04",
        }

    @staticmethod
    def _is_demo_stop(text: str) -> bool:
        normalized = text.strip().lower()
        return normalized in {
            "/stop demo01",
            "/stop demo02",
            "/stop demo03",
            "/stop demo04",
            "/stop demo",
            "stop demo01",
            "stop demo02",
            "stop demo03",
            "stop demo04",
            "stop demo",
            "停止 demo01",
            "停止 demo02",
            "停止 demo03",
            "停止 demo04",
            "停止 demo",
            "中止 demo01",
            "中止 demo02",
            "中止 demo03",
            "中止 demo04",
            "取消 demo01",
            "取消 demo02",
            "取消 demo03",
            "取消 demo04",
        }

    async def on_chat_input_command_requested(self, event: ChatInput.CommandRequested) -> None:
        """Open the command palette from the chat input controls."""
        event.stop()
        await self.app.action_toggle_command_palette()

