"""Benchmark session runtime for StarDojo tasks over the bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable

from .obs_compact import to_jsonable


class BenchmarkError(RuntimeError):
    """User-facing benchmark session error."""


TaskLoader = Callable[[str, int], Any]
ProxyFactory = Callable[[int], Any]


@dataclass
class BenchmarkSession:
    task_name: str
    task_id: int
    task: Any
    task_proxy: Any
    max_steps: int
    step: int = 0
    completed: bool = False
    truncated: bool = False
    last_eval: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)


class BenchmarkRuntime:
    """Manage one active StarDojo benchmark task session.

    The Agent still receives compact bridge observations. The evaluator receives
    raw StarDojo observations so StarDojo's original task logic can inspect
    fields such as Progression, farm, CurrentMenuData, and callbackdata.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        task_loader: TaskLoader | None = None,
        proxy_factory: ProxyFactory | None = None,
    ) -> None:
        self.runtime = runtime
        self.task_loader = task_loader or _load_task
        self.proxy_factory = proxy_factory or _make_task_proxy
        self._lock = Lock()
        self._session: BenchmarkSession | None = None

    def start(self, task_name: str, task_id: int, max_steps: int | None = None) -> dict[str, Any]:
        """Start a benchmark session and return the initial observation/result."""

        task_name = _validate_task_name(task_name)
        task_id = _validate_task_id(task_id)
        if max_steps is not None:
            max_steps = _validate_max_steps(max_steps)

        with self._lock:
            task = self.task_loader(task_name, task_id)
            if task is None:
                raise BenchmarkError(f"Unknown benchmark task: {task_name}[{task_id}]")

            task_proxy = self.proxy_factory(_runtime_port(self.runtime))
            max_steps = max_steps or _default_max_steps(task)
            raw_obs = self.runtime.start_benchmark_task(task, task_proxy)
            eval_result = self._evaluate(task, raw_obs, task_proxy)

            self._session = BenchmarkSession(
                task_name=task_name,
                task_id=task_id,
                task=task,
                task_proxy=task_proxy,
                max_steps=max_steps,
                completed=bool(eval_result.get("completed", False)),
                last_eval=eval_result,
            )
            return self._response(raw_obs)

    def status(self) -> dict[str, Any]:
        """Return the current benchmark session status."""

        with self._lock:
            return self._status_unlocked()

    def execute(self, action: str) -> dict[str, Any]:
        """Execute one action and evaluate the active benchmark task."""

        action = _validate_action(action)
        with self._lock:
            session = self._require_session()
            if session.completed:
                raise BenchmarkError("Benchmark session is already completed.")
            if session.truncated:
                raise BenchmarkError("Benchmark session already reached max_steps.")

            raw_obs = self.runtime.execute_raw(action)
            eval_result = self._evaluate(session.task, raw_obs, session.task_proxy)

            knocked_out = self._check_knockout(raw_obs)
            if knocked_out:
                session.truncated = True
                session.knocked_out = True
                session.last_eval = {"completed": False, "quantity": 0, "truncated": True, "reason": "knocked_out"}

            session.step += 1
            session.completed = bool(eval_result.get("completed", False))
            if not knocked_out:
                session.truncated = session.step >= session.max_steps and not session.completed
            session.last_eval = eval_result
            session.history.append(
                {
                    "step": session.step,
                    "action": action,
                    "eval": eval_result,
                    "completed": session.completed,
                    "truncated": session.truncated,
                    "knocked_out": knocked_out,
                }
            )
            return self._response(raw_obs)

    def stop(self) -> dict[str, Any]:
        """Stop the active session and return its final status."""

        with self._lock:
            status = self._status_unlocked()
            self._session = None
            status["active"] = False
            status["stopped"] = True
            return status

    @staticmethod
    def _normalize_obs_keys(obs: dict[str, Any]) -> dict[str, Any]:
        inv = obs.get("inventory")
        if isinstance(inv, list):
            for item in inv:
                if isinstance(item, dict):
                    if "Name" not in item and "name" in item:
                        item["Name"] = item["name"]
                    if "Quantity" not in item and "quantity" in item:
                        item["Quantity"] = item["quantity"]
        return obs

    def _evaluate(self, task: Any, raw_obs: dict[str, Any], task_proxy: Any) -> dict[str, Any]:
        self._normalize_obs_keys(raw_obs)
        result = task.evaluate(raw_obs, task_proxy)
        if not isinstance(result, dict):
            raise BenchmarkError(f"Task evaluator returned {type(result).__name__}")
        result = to_jsonable(result)
        result.setdefault("completed", False)
        result.setdefault("quantity", getattr(task, "current_quantity", 0))
        return result

    @staticmethod
    def _check_knockout(raw_obs: dict[str, Any]) -> bool:
        health = raw_obs.get("health")
        try:
            if health is not None and float(health) <= 0:
                return True
        except (ValueError, TypeError):
            pass
        location = str(raw_obs.get("location", ""))
        if location in ("Hospital", "hospital"):
            return True
        current_menu = raw_obs.get("current_menu", {})
        if isinstance(current_menu, dict):
            menu_type = str(current_menu.get("type", "")).lower()
            if menu_type == "dialogue":
                dialogues = current_menu.get("dialogues", [])
                if isinstance(dialogues, list) and len(dialogues) > 0:
                    msg_text = str(dialogues[0]).lower() if dialogues else ""
                    if any(w in msg_text for w in ("knocked", "passed out", "unconscious", "bring you")):
                        return True
                return True
        return False

    def _response(self, raw_obs: dict[str, Any]) -> dict[str, Any]:
        return {
            "obs": self.runtime.format_observation(raw_obs),
            "benchmark": self._status_unlocked(),
        }

    def _status_unlocked(self) -> dict[str, Any]:
        session = self._session
        if session is None:
            return {"active": False}

        task = session.task
        return {
            "active": True,
            "task_name": session.task_name,
            "task_id": session.task_id,
            "description": getattr(task, "llm_description", None),
            "object": getattr(task, "object", None),
            "target_quantity": getattr(task, "quantity", None),
            "tool": getattr(task, "tool", None),
            "evaluator": getattr(task, "evaluator", None),
            "difficulty": getattr(task, "difficulty", None),
            "step": session.step,
            "max_steps": session.max_steps,
            "completed": session.completed,
            "truncated": session.truncated,
            "knocked_out": getattr(session, "knocked_out", False),
            "eval": session.last_eval,
        }

    def _require_session(self) -> BenchmarkSession:
        if self._session is None:
            raise BenchmarkError("No active benchmark session. Call /benchmark/start first.")
        return self._session


def _load_task(task_name: str, task_id: int) -> Any:
    try:
        from env.tasks.utils.load_task import load_task
    except Exception as exc:
        raise RuntimeError("Failed to import StarDojo benchmark task loader.") from exc
    return load_task(task_name, task_id)


def _make_task_proxy(port: int) -> Any:
    try:
        from env.tasks.utils.init_task import InitTaskProxy
    except Exception as exc:
        raise RuntimeError("Failed to import StarDojo InitTaskProxy.") from exc
    return InitTaskProxy(port)


def _default_max_steps(task: Any) -> int:
    difficulty = getattr(task, "difficulty", None)
    if difficulty == "easy":
        return 30
    if difficulty == "medium":
        return 50
    return 200


def _runtime_port(runtime: Any) -> int:
    port = getattr(runtime, "stardojo_port", None)
    if not isinstance(port, int):
        raise BenchmarkError("Runtime does not expose an integer stardojo_port.")
    return port


def _validate_task_name(task_name: Any) -> str:
    if not isinstance(task_name, str) or not task_name.strip():
        raise BenchmarkError("Missing non-empty string field: task_name")
    return task_name.strip()


def _validate_task_id(task_id: Any) -> int:
    if isinstance(task_id, bool) or not isinstance(task_id, int):
        raise BenchmarkError("Missing integer field: task_id")
    if task_id < 0:
        raise BenchmarkError("task_id must be >= 0")
    return task_id


def _validate_max_steps(max_steps: Any) -> int:
    if isinstance(max_steps, bool) or not isinstance(max_steps, int):
        raise BenchmarkError("max_steps must be an integer")
    if max_steps <= 0:
        raise BenchmarkError("max_steps must be > 0")
    return max_steps


def _validate_action(action: Any) -> str:
    if not isinstance(action, str) or not action.strip():
        raise BenchmarkError("Missing non-empty string field: action")
    return action.strip()
