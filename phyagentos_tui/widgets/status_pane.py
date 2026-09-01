"""Compact live status pane for the tiling chat screen."""

from textual.widgets import Static


class StatusPane(Static):
    """Shows model, gateway and channel status in the side column."""

    def __init__(self) -> None:
        super().__init__()
        self._demo_mode = False

    def on_mount(self) -> None:
        self.refresh_status()

    def refresh_status(self) -> None:
        if self._demo_mode:
            return
        config = self.app.config
        gateway = getattr(self.app, "_gateway_service", None)

        if gateway is None:
            gw_status = "not initialized"
        elif gateway.error:
            detail = str(gateway.error).strip().replace("\n", " ")
            if len(detail) > 96:
                detail = detail[:93] + "..."
            gw_status = f"error: {detail}"
        elif gateway.is_running:
            gw_status = "running"
        else:
            gw_status = "starting..."

        enabled = 0
        try:
            from PhyAgentOS.channels.registry import discover_channel_names

            for modname in discover_channel_names():
                section = getattr(config.channels, modname, None)
                if section and getattr(section, "enabled", False):
                    enabled += 1
        except Exception:
            pass

        self.update(
            f"Model: {config.agents.defaults.model}\n"
            f"Gateway: {gw_status}\n"
            f"Channels: {enabled} enabled"
        )

    def show_demo_status(self, title: str, rows: dict[str, str]) -> None:
        """Replace the side pane with a compact live demo dashboard."""
        self._demo_mode = True
        lines = [title, ""]
        for key, value in rows.items():
            lines.append(f"{key:<12} {value}")
        self.update("\n".join(lines))

    def clear_demo_status(self) -> None:
        self._demo_mode = False
        self.refresh_status()

