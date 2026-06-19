"""Runtime wrapper around StarDojo and its SkillExecutor."""

from __future__ import annotations

from pathlib import Path
import sys
from threading import Lock
from typing import Any

from .action_parser import execute_skill_expression
from .obs_compact import compact_obs, image_paths_from_obs, to_jsonable


class StardewRuntime:
    """Long-lived StarDojo runtime used by the HTTP bridge."""

    def __init__(
        self,
        *,
        stardojo_port: int = 10783,
        stardojo_root: str | Path | None = None,
        image_save_path: str | Path | None = "screen_shot_buffer",
        compact: bool = True,
    ) -> None:
        self.stardojo_port = stardojo_port
        self.stardojo_root = Path(stardojo_root) if stardojo_root is not None else _default_stardojo_root()
        self.image_save_path = str(image_save_path) if image_save_path is not None else None
        self.image_base_path = self._resolve_image_base_path(image_save_path)
        self.compact = compact
        self.latest_image_path: Path | None = None
        self._lock = Lock()

        self._configure_import_paths()
        self.env, self.skill_executor = self._build_stardojo()

    def observe(self) -> dict[str, Any]:
        """Return the current StarDojo observation."""

        with self._lock:
            raw_obs = self._observe_raw_unlocked()
            return self.format_observation(raw_obs)

    def observe_raw(self) -> dict[str, Any]:
        """Return the raw StarDojo observation for benchmark evaluators."""

        with self._lock:
            return self._observe_raw_unlocked()

    def execute(self, action: str) -> dict[str, Any]:
        """Execute one Track A action string and return the next observation."""

        with self._lock:
            execute_skill_expression(self.skill_executor, action)
            raw_obs = self._observe_raw_unlocked()
            return self.format_observation(raw_obs)

    def execute_raw(self, action: str) -> dict[str, Any]:
        """Execute one action and return the raw StarDojo observation."""

        with self._lock:
            execute_skill_expression(self.skill_executor, action)
            return self._observe_raw_unlocked()

    def start_benchmark_task(self, task: Any, task_proxy: Any) -> dict[str, Any]:
        """Run init_commands only (save already loaded during bridge startup)."""

        with self._lock:
            action_proxy = getattr(self.env, "action_proxy", None)
            wait_for_server = getattr(action_proxy, "wait_for_server", None)
            if callable(wait_for_server):
                wait_for_server()
            init_commands = getattr(task, "init_commands", None) or []
            if init_commands:
                execute_skills(self.skill_executor, init_commands)
            return self._observe_raw_unlocked()

    def format_observation(self, obs: dict[str, Any]) -> dict[str, Any]:
        """Format a raw StarDojo observation for HTTP responses."""

        if self.compact:
            return compact_obs(obs)
        return to_jsonable(obs)

    def _observe_raw_unlocked(self) -> dict[str, Any]:
        obs = self.env._get_obs()
        self._remember_latest_image_path(obs)
        return obs

    def _remember_latest_image_path(self, obs: Any) -> None:
        if not isinstance(obs, dict):
            return
        for image_path in reversed(image_paths_from_obs(obs)):
            path = self.resolve_image_path(image_path)
            if path.is_file():
                self.latest_image_path = path
                return

    def resolve_image_path(self, image_path: str | Path) -> Path:
        path = Path(image_path)
        if path.is_absolute():
            return path
        if self.image_base_path is not None:
            rel = Path(str(path).replace("\\", "/"))
            if rel.parts and self.image_base_path.name and rel.parts[0] == self.image_base_path.name:
                rel = Path(*rel.parts[1:]) if len(rel.parts) > 1 else Path()
            return self.image_base_path / rel
        return self.stardojo_root / path

    def _resolve_image_base_path(self, image_save_path: str | Path | None) -> Path | None:
        if image_save_path is None:
            return None
        path = Path(image_save_path)
        if path.is_absolute():
            return path
        return self.stardojo_root / path

    def _configure_import_paths(self) -> None:
        root = self.stardojo_root.resolve()
        candidates = (
            root,
            root / "env",
            root / "agent",
            root / "agent" / "stardojo",
        )
        for candidate in reversed(candidates):
            candidate_str = str(candidate)
            if candidate.exists() and candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)

    def _build_stardojo(self):
        try:
            from stardew_env import StarDojo
            from .skill_executor import SkillExecutor
        except Exception as exc:
            raise RuntimeError(
                "Failed to import StarDojo. Start the bridge from the Windows "
                "stardojo micromamba environment or pass --stardojo-root."
            ) from exc

        env = StarDojo(
            port=self.stardojo_port,
            new_game=False,
            image_save_path=self.image_save_path,
        )
        return env, SkillExecutor(env.action_proxy)


def _default_stardojo_root() -> Path:
    return Path(__file__).resolve().parent.parent / "stardojo"

