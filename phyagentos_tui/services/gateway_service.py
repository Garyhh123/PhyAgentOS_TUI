"""Gateway lifecycle service for TUI."""

import asyncio
from typing import TYPE_CHECKING

from PhyAgentOS.config.schema import Config

if TYPE_CHECKING:
    from textual.app import App


class GatewayService:
    """Manages gateway services (Cron, Heartbeat, Channels) lifecycle within TUI."""

    def __init__(self, config: Config, app: "App") -> None:
        self.config = config
        self.app = app
        self._agent = None
        self._cron = None
        self._heartbeat = None
        self._channels = None
        self._bus = None
        self._forge_tool_client = None
        self._forge_tool_invocation_ids = None
        self._forge_task_coordinator = None
        self._runtime_availability_provider = None
        self._running = False
        self._error: str | None = None
        self._tasks: list[asyncio.Task] = []

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def agent(self):
        return self._agent

    @property
    def bus(self):
        return self._bus

    @property
    def forge_orchestrator(self):
        return self._forge_task_coordinator

    @property
    def error(self) -> str | None:
        return self._error

    async def start(self) -> None:
        """Start all gateway services. Gracefully handles missing configuration."""
        from PhyAgentOS.bus.queue import MessageBus

        self._bus = MessageBus()

        try:
            await self._start_services()
        except Exception as e:
            self._error = str(e)
            self.app.log.warning(f"Gateway not started: {e}")

    async def _start_services(self) -> None:
        """Create and start provider, agent, cron, heartbeat and channels."""
        from PhyAgentOS.agent.loop import AgentLoop
        from PhyAgentOS.channels.manager import ChannelManager
        from PhyAgentOS.config.paths import get_cron_dir
        from PhyAgentOS.cron.service import CronService
        from PhyAgentOS.cron.types import CronJob
        from PhyAgentOS.embodiment_registry import EmbodimentRegistry
        from PhyAgentOS.heartbeat.service import HeartbeatService
        from PhyAgentOS.session.manager import SessionManager
        from PhyAgentOS.utils.helpers import sync_workspace_templates

        from PhyAgentOS.cli.commands import _make_forge_components, _make_provider

        config = self.config
        registry = EmbodimentRegistry(config)
        if registry.is_fleet:
            registry.sync_layout()
        else:
            sync_workspace_templates(config.workspace_path)

        defaults = config.agents.defaults
        provider = _make_provider(config)
        (
            self._forge_tool_client,
            self._forge_tool_invocation_ids,
            self._forge_task_coordinator,
            self._runtime_availability_provider,
        ) = _make_forge_components(config, provider)

        # Cron
        cron_store_path = get_cron_dir() / "jobs.json"
        self._cron = CronService(cron_store_path)

        # Agent
        session_manager = SessionManager(config.workspace_path)
        self._agent = AgentLoop(
            bus=self._bus,
            provider=provider,
            workspace=config.workspace_path,
            model=defaults.model,
            max_iterations=defaults.max_tool_iterations,
            context_window_tokens=defaults.context_window_tokens,
            brave_api_key=config.tools.web.search.api_key or None,
            web_proxy=config.tools.web.proxy or None,
            exec_config=config.tools.exec,
            cron_service=self._cron,
            restrict_to_workspace=config.tools.restrict_to_workspace,
            session_manager=session_manager,
            mcp_servers=config.tools.mcp_servers,
            channels_config=config.channels,
            embodiment_registry=registry,
            forge_tool_client=self._forge_tool_client,
            forge_tool_invocation_ids=self._forge_tool_invocation_ids,
            forge_task_coordinator=self._forge_task_coordinator,
            runtime_availability_provider=self._runtime_availability_provider,
            evolution_config=config.agents.evolution,
            evolution_provider=provider,
            evolution_model=config.agents.evolution.model,
        )

        # Cron callback
        async def on_cron_job(job: CronJob) -> str | None:
            from PhyAgentOS.agent.tools.cron import CronTool
            from PhyAgentOS.agent.tools.message import MessageTool

            reminder_note = (
                "[Scheduled Task] Timer finished.\n\n"
                f"Task '{job.name}' has been triggered.\n"
                f"Scheduled instruction: {job.payload.message}"
            )
            cron_tool = self._agent.tools.get("cron")
            cron_token = None
            if isinstance(cron_tool, CronTool):
                cron_token = cron_tool.set_cron_context(True)
            try:
                response = await self._agent.process_direct(
                    reminder_note,
                    session_key=f"cron:{job.id}",
                    channel=job.payload.channel or "cli",
                    chat_id=job.payload.to or "direct",
                )
            finally:
                if isinstance(cron_tool, CronTool) and cron_token is not None:
                    cron_tool.reset_cron_context(cron_token)

            message_tool = self._agent.tools.get("message")
            if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
                return response

            if job.payload.deliver and job.payload.to and response:
                from PhyAgentOS.bus.events import OutboundMessage

                await self._bus.publish_outbound(OutboundMessage(
                    channel=job.payload.channel or "cli",
                    chat_id=job.payload.to,
                    content=response,
                ))
            return response

        self._cron.on_job = on_cron_job

        # Channels
        self._channels = ChannelManager(config, self._bus)

        def _pick_heartbeat_target() -> tuple[str, str]:
            enabled = set(self._channels.enabled_channels)
            for item in session_manager.list_sessions():
                key = item.get("key") or ""
                if ":" not in key:
                    continue
                channel, chat_id = key.split(":", 1)
                if channel in {"cli", "system"}:
                    continue
                if channel in enabled and chat_id:
                    return channel, chat_id
            return "cli", "direct"

        # Heartbeat
        hb_cfg = config.gateway.heartbeat

        async def on_heartbeat_execute(tasks: str) -> str:
            async def _silent(*_args, **_kwargs):
                pass
            channel, chat_id = _pick_heartbeat_target()
            return await self._agent.process_direct(
                tasks,
                session_key="heartbeat",
                channel=channel,
                chat_id=chat_id,
                on_progress=_silent,
            )

        async def on_heartbeat_notify(response: str) -> None:
            from PhyAgentOS.bus.events import OutboundMessage
            channel, chat_id = _pick_heartbeat_target()
            if channel == "cli":
                return
            await self._bus.publish_outbound(
                OutboundMessage(channel=channel, chat_id=chat_id, content=response)
            )

        self._heartbeat = HeartbeatService(
            workspace=config.workspace_path,
            provider=provider,
            model=self._agent.model,
            on_execute=on_heartbeat_execute,
            on_notify=on_heartbeat_notify,
            interval_s=hb_cfg.interval_s,
            enabled=hb_cfg.enabled,
        )

        # Start all services
        await self._cron.start()
        await self._heartbeat.start()
        self._tasks.append(asyncio.create_task(self._agent.run()))
        self._tasks.append(asyncio.create_task(self._channels.start_all()))
        self._running = True

    async def stop(self) -> None:
        """Stop all gateway services."""
        self._running = False
        if self._heartbeat:
            self._heartbeat.stop()
        if self._cron:
            self._cron.stop()
        if self._agent:
            self._agent.stop()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._channels:
            await self._channels.stop_all()
        if self._agent:
            await self._agent.close_mcp()

