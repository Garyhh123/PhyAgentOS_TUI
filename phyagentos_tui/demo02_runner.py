"""Temporary Demo 02 runner placeholder.

The TUI can start and run against the current core while Demo 02 is migrated to
the new AgentTask + Tool API path.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any


EventSink = Callable[[dict[str, Any]], Awaitable[None] | None]


class Demo02Runner:
    """Keep the optional demo entry from breaking the TUI during core updates."""

    progress_delays_s = (1.0,)
    final_delay_s = 0.5

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()

    async def run(self, sink: EventSink) -> None:
        await self._emit(
            sink,
            {
                "kind": "reset",
                "title": "Demo 02",
                "description": "Demo 02 is paused while the TUI is being aligned with the latest core.",
                "stages": ["paused"],
                "dashboard": {
                    "AgentTask": "paused",
                    "Forge": "core updated",
                    "Evidence": "not started",
                    "Verifier": "not started",
                },
            },
        )
        await self._emit(
            sink,
            {
                "kind": "stage",
                "stage": 0,
                "status": "success",
                "message": "TUI shell is available; Demo 02 migration can be resumed later.",
            },
        )
        await self._emit(sink, {"kind": "done", "status": "paused"})

    async def stop(self) -> None:
        return None

    @staticmethod
    async def _emit(sink: EventSink, event: dict[str, Any]) -> None:
        result = sink(event)
        if inspect.isawaitable(result):
            await result

