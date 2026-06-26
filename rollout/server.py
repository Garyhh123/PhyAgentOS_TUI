"""WebSocket rollout server.

Isaac Sim / Kit must run on the process **main thread**. The sync websockets server
invokes ``handle()`` on a per-connection worker thread, so sim work is queued back
to the main thread.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rollout.protocol import RolloutRequest, RolloutResponse, decode_message, encode_message

logger = logging.getLogger(__name__)

# reset / first Isaac boot can take many minutes
_SIM_REQUEST_TIMEOUT_S = 3600.0

try:
    from websockets.sync.server import serve as sync_serve
except ImportError as exc:  # pragma: no cover
    raise ImportError("websockets>=16 required (sync server)") from exc


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).expanduser().resolve()
    with config_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def create_runner(config: dict[str, Any], *, gui: bool) -> Any:
    runner_kind = str(config.get("runner", "pipergo2_manipulation")).strip().lower()
    if runner_kind in ("merom_multi_robot", "multi_robot", "merom"):
        from rollout.merom_multi_robot_runner import MeromMultiRobotRunner

        return MeromMultiRobotRunner(config, gui=gui)
    from rollout.pipergo2_runner import PiperGo2ManipulationRunner

    return PiperGo2ManipulationRunner(config, gui=gui)


@dataclass
class _PendingRequest:
    request: RolloutRequest
    response_queue: queue.Queue[RolloutResponse]


class RolloutServer:
    """Single-client rollout WebSocket server (one Isaac Sim env per process)."""

    def __init__(self, runner: Any):
        self.runner = runner
        self._pending: queue.Queue[_PendingRequest] = queue.Queue()
        self._shutdown = threading.Event()

    def handle(self, websocket: Any) -> None:
        """Runs on a websockets worker thread — only enqueue, never touch Isaac here."""
        peer = getattr(websocket, "remote_address", None)
        logger.info("client connected: %s", peer)
        try:
            for raw in websocket:
                if isinstance(raw, str):
                    raw = raw.encode("utf-8")
                try:
                    data = decode_message(raw)
                    request = RolloutRequest.from_dict(data)
                except Exception as exc:
                    err = RolloutResponse(
                        type="error",
                        ok=False,
                        error=f"invalid message: {exc}",
                    )
                    websocket.send(encode_message(err.to_dict()))
                    continue

                resp_q: queue.Queue[RolloutResponse] = queue.Queue(maxsize=1)
                self._pending.put(_PendingRequest(request, resp_q))
                try:
                    response = resp_q.get(timeout=_SIM_REQUEST_TIMEOUT_S)
                except queue.Empty:
                    response = RolloutResponse.from_request(
                        request,
                        ok=False,
                        error="sim request timed out on main thread",
                    )
                websocket.send(encode_message(response.to_dict()))
        except Exception as exc:
            if type(exc).__name__ != "ConnectionClosed":
                logger.info("client disconnected: %s (%s)", peer, exc)
            else:
                logger.info("client disconnected: %s", peer)

    def run_main_loop(self) -> None:
        """Process sim requests on the main thread (Isaac-safe)."""
        while not self._shutdown.is_set():
            try:
                pending = self._pending.get(timeout=0.25)
            except queue.Empty:
                continue
            request = pending.request
            try:
                payload = self._handle_sync(request)
                pending.response_queue.put(
                    RolloutResponse.from_request(request, ok=True, payload=payload)
                )
            except Exception as exc:
                logger.exception("request %s failed", request.type)
                pending.response_queue.put(
                    RolloutResponse.from_request(request, ok=False, error=str(exc))
                )

    def _handle_sync(self, request: RolloutRequest) -> dict[str, Any]:
        req_type = request.type.lower()
        payload = request.payload

        if req_type == "health":
            return self.runner.health()
        if req_type == "reset":
            logger.info("reset: starting Isaac/InternUtopia (may take several minutes on first boot)")
            return self.runner.reset(payload)
        if req_type in ("step", "observe", "close"):
            logger.info("main-thread %s (session=%s)", req_type, request.session_id or "-")
        if req_type == "observe":
            return {"obs": self.runner.observe()}
        if req_type == "step":
            return self.runner.step(payload)
        if req_type == "close":
            return self.runner.close()
        raise ValueError(f"unsupported request type: {request.type}")


def _run_ws_server(server: RolloutServer, host: str, port: int) -> None:
    with sync_serve(server.handle, host, port, max_size=None) as ws_server:
        ws_server.serve_forever()


def serve_blocking(
    host: str,
    port: int,
    config: dict[str, Any],
    *,
    gui: bool,
) -> None:
    """Run until KeyboardInterrupt. WS I/O on a side thread; Isaac on the main thread."""
    runner = create_runner(config, gui=gui)
    server = RolloutServer(runner)
    ws_thread = threading.Thread(
        target=_run_ws_server,
        args=(server, host, port),
        name="rollout-ws",
        daemon=True,
    )
    ws_thread.start()
    logger.info(
        "rollout server listening on ws://%s:%s (gui=%s, main_thread_sim=True)",
        host,
        port,
        gui,
    )
    try:
        server.run_main_loop()
    except KeyboardInterrupt:
        print("\n[rollout] stopped", flush=True)
    finally:
        server._shutdown.set()
        logger.info("shutting down rollout runner")
        try:
            runner.close()
        except Exception as exc:
            logger.warning("runner close on shutdown failed: %s", exc)


async def serve(
    host: str,
    port: int,
    config: dict[str, Any],
    *,
    gui: bool,
) -> None:
    """Deprecated asyncio entry."""
    del host, port, config, gui
    raise RuntimeError("use serve_blocking(); asyncio server conflicts with Isaac Sim GUI")
