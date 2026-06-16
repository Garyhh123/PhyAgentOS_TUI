"""Runtime wrapper around StarDojo and its SkillExecutor."""

from __future__ import annotations

import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path
import sys
from threading import Lock
from typing import Any

from .action_parser import execute_skill_expression
from .obs_compact import compact_obs, image_paths_from_obs, to_jsonable


class RuntimeBusyError(RuntimeError):
    """Raised when a previous StarDojo call is still running."""


class StardewRuntime:
    """Long-lived StarDojo runtime used by the HTTP bridge."""

    def __init__(
        self,
        *,
        stardojo_port: int = 10783,
        stardojo_root: str | Path | None = None,
        stardew_app_path: str | Path | None = None,
        image_save_path: str | Path | None = "screen_shot_buffer",
        compact: bool = True,
    ) -> None:
        self.stardojo_port = stardojo_port
        self.stardojo_root = Path(stardojo_root) if stardojo_root is not None else _default_stardojo_root()
        self.stardew_app_path = str(stardew_app_path) if stardew_app_path is not None else None
        self.image_save_path = str(image_save_path) if image_save_path is not None else None
        self.image_base_path = self._resolve_image_base_path(image_save_path)
        self.compact = compact
        self.latest_image_path: Path | None = None
        self._lock = Lock()
        self.lock_timeout = 5.0

        self._configure_import_paths()
        self._configure_stardojo_environment()
        self.env, self.skill_executor = self._build_stardojo()

    def observe(self) -> dict[str, Any]:
        """Return the current StarDojo observation."""

        with self._runtime_lock():
            raw_obs = self._observe_raw_unlocked()
            return self.format_observation(raw_obs)

    def observe_raw(self) -> dict[str, Any]:
        """Return the raw StarDojo observation for benchmark evaluators."""

        with self._runtime_lock():
            return self._observe_raw_unlocked()

    def execute(self, action: str) -> dict[str, Any]:
        """Execute one Track A action string and return the next observation."""

        with self._runtime_lock():
            execute_skill_expression(self.skill_executor, action)
            raw_obs = self._observe_raw_unlocked()
            return self.format_observation(raw_obs)

    def execute_raw(self, action: str) -> dict[str, Any]:
        """Execute one action and return the raw StarDojo observation."""

        with self._runtime_lock():
            execute_skill_expression(self.skill_executor, action)
            return self._observe_raw_unlocked()

    def start_benchmark_task(self, task: Any, task_proxy: Any) -> dict[str, Any]:
        """Initialize a StarDojo benchmark task and return its raw baseline obs."""

        with self._runtime_lock(timeout=1.0):
            action_proxy = getattr(self.env, "action_proxy", None)
            wait_for_server = getattr(action_proxy, "wait_for_server", None)
            if callable(wait_for_server):
                wait_for_server()
            with self._stardojo_env_workdir():
                task.init_task(task_proxy)
            # The bridge uses StarDojo observe_v2 over TCP. The original LLM runner
            # initializes an mmap reader here, but some Windows installs do not
            # create shared_memory_<port>.bin, while /observe still works fine.
            return self._observe_raw_unlocked()

    @contextmanager
    def _runtime_lock(self, timeout: float | None = None):
        acquired = self._lock.acquire(timeout=self.lock_timeout if timeout is None else timeout)
        if not acquired:
            raise RuntimeBusyError("Stardew runtime is busy. A previous game call may still be waiting for SMAPI; do not issue another Stardew action yet.")
        try:
            yield
        finally:
            self._lock.release()

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

    @contextmanager
    def _stardojo_env_workdir(self):
        # Some upstream benchmark helpers use paths such as tasks/saves relative
        # to stardojo/env. Keep that assumption local to the StarDojo call.
        previous = Path.cwd()
        os.chdir(self.stardojo_root / "env")
        try:
            yield
        finally:
            os.chdir(previous)

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

    def _configure_stardojo_environment(self) -> None:
        # Upstream StarDojo reads STARDEW_APP_PATH at import time. The bridge
        # attaches to an already-running SMAPI instance, so this path is only
        # needed when a caller wants StarDojo itself to launch the game.
        if self.stardew_app_path is not None:
            os.environ["STARDEW_APP_PATH"] = self.stardew_app_path
            return
        os.environ.setdefault("STARDEW_APP_PATH", "")

    def _patch_optional_env_actions_module(self) -> None:
        try:
            from env.actions import ActionProxy as EnvActionProxy
        except Exception:
            return
        _patch_action_proxy_post_message(EnvActionProxy)

    def _build_stardojo(self):
        try:
            from stardew_env import StarDojo
            import actions as stardew_actions
        except Exception as exc:
            raise RuntimeError(
                "Failed to import StarDojo. Start the bridge from the Windows "
                "stardojo micromamba environment or pass --stardojo-root."
            ) from exc

        # stardew_env.py imports top-level `actions`, not `env.actions`.
        # Patch the exact ActionProxy class used by StarDojo instances.
        _patch_action_proxy_post_message(stardew_actions.ActionProxy)
        self._patch_optional_env_actions_module()

        env = StarDojo(
            port=self.stardojo_port,
            new_game=False,
            image_save_path=self.image_save_path,
        )
        return env, BridgeSkillExecutor(env.action_proxy)




def _patch_action_proxy_post_message(action_proxy_class: Any) -> None:
    if getattr(action_proxy_class, "_phyagentos_fast_recv", False):
        return

    def _post_message(self, message: str, print_message: bool = True) -> str:
        client_socket = None
        response: list[bytes] = []
        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if "observe" in message or "get_surroundings" in message or "wait_for_server" in message:
                client_socket.settimeout(120)
            else:
                # Small actions such as choose_item can still wait for the SMAPI
                # main thread. Five seconds is too aggressive and causes false
                # timeouts that make the agent retry while the old call is alive.
                client_socket.settimeout(max(float(getattr(self, "timeout", 5)), 30.0))

            result = client_socket.connect_ex(("127.0.0.1", self.port))
            reconnect_time = 0
            while result != 0:
                if reconnect_time > 10:
                    raise AssertionError("reconnect too many time, the game need restart!")
                time.sleep(1)
                result = client_socket.connect_ex(("127.0.0.1", self.port))
                reconnect_time += 1

            client_socket.sendall(message.encode("utf-8"))
            is_legacy_observe = "observe" in message and "observe_v2" not in message
            if is_legacy_observe:
                return self.mmap_reader.read_from_mmap()

            eof = b"<EOF>"
            tail = b""
            recv_start = time.perf_counter()
            while True:
                data = client_socket.recv(65536)
                if not data:
                    break
                response.append(data)
                tail = (tail + data)[-len(eof):]
                if tail == eof:
                    break

            recv_done = time.perf_counter()
            payload = b"".join(response)
            if payload.endswith(eof):
                payload = payload[:-len(eof)]
            text = payload.decode("utf-8")
            decode_done = time.perf_counter()
            if "observe" in message or "get_surroundings" in message:
                print(
                    "PhyAgentOS fast recv %s: chunks=%d bytes=%d recv=%.3fs join_decode=%.3fs"
                    % (message, len(response), len(payload), recv_done - recv_start, decode_done - recv_done)
                )
            return text
        except AssertionError as exc:
            raise AssertionError("got a Error: %s" % (exc,)) from exc
        except Exception as exc:
            if print_message:
                preview = b"".join(response)[:80].decode("utf-8", errors="replace")
                print(message.encode("utf-8"))
                print("Error: %s" % (exc,))
                print("response from server(sample): %s" % preview)
            raise
        finally:
            if client_socket:
                client_socket.close()

    action_proxy_class._post_message = _post_message
    action_proxy_class._phyagentos_fast_recv = True
    print("PhyAgentOS Stardew bridge patched fast ActionProxy recv:", action_proxy_class)

class BridgeSkillExecutor:
    """Minimal StarDojo skill executor used by the HTTP bridge."""

    def __init__(self, action_proxy: Any) -> None:
        self.action_proxy = action_proxy

    def move(self, x: int, y: int) -> Any:
        return self.action_proxy.move(x, y)

    def use(self, direction: str) -> Any:
        return self.action_proxy.use(_direction_to_int(direction))

    def interact(self, direction: str) -> Any:
        return self.action_proxy.interact(_direction_to_int(direction))

    def choose_item(self, slot_index: int) -> Any:
        return self.action_proxy.choose_item(slot_index)

    def choose_option(self, option_index: int, quantity: int | None = None, direction: str | None = None) -> Any:
        return self.action_proxy.choose_option(option_index, quantity, _option_direction_to_int(direction))

    def attach_item(self, slot_index: int) -> Any:
        return self.action_proxy.attach_item(slot_index)

    def unattach_item(self) -> Any:
        return self.action_proxy.unattach_item()

    def craft(self, item: str) -> Any:
        return self.action_proxy._post_message("craft%" + item)

    def menu(self, option: str, menu_name: str) -> Any:
        if option == "close":
            return self.action_proxy.exit_menu()
        if option == "open" and menu_name == "map":
            return self.action_proxy.open_map()
        raise ValueError("Unsupported menu action: menu(%r, %r)" % (option, menu_name))


def _direction_to_int(direction: str) -> int:
    directions = {"up": 0, "right": 1, "down": 2, "left": 3}
    try:
        return directions[direction]
    except KeyError as exc:
        raise ValueError("Unsupported direction: %r" % (direction,)) from exc


def _option_direction_to_int(direction: str | None) -> int:
    if direction is None:
        return 0
    directions = {"in": 0, "out": 1}
    try:
        return directions[direction]
    except KeyError as exc:
        raise ValueError("Unsupported option direction: %r" % (direction,)) from exc


def _default_stardojo_root() -> Path:
    return Path(__file__).resolve().parent.parent / "stardojo"

