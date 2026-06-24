"""B1K-compatible websocket policy server (no omnigibson import).

Vendored from ``omnigibson.learning.utils.network_utils`` so the openpi uv venv
does not need OmniGibson / numba / coverage.
"""

from __future__ import annotations

import asyncio
import functools
import http
import logging
import time
import traceback
from copy import deepcopy
from typing import Any, Optional

import msgpack
import numpy as np
import websockets
import websockets.asyncio.server as _server

logger = logging.getLogger(__name__)


def pack_array(obj: Any) -> Any:
    if isinstance(obj, (np.ndarray, np.generic)) and obj.dtype.kind in ("V", "O", "c"):
        raise ValueError(f"Unsupported dtype: {obj.dtype}")
    if isinstance(obj, np.ndarray):
        return {
            b"__ndarray__": True,
            b"data": obj.tobytes(),
            b"dtype": obj.dtype.str,
            b"shape": obj.shape,
        }
    if isinstance(obj, np.generic):
        return {
            b"__npgeneric__": True,
            b"data": obj.item(),
            b"dtype": obj.dtype.str,
        }
    return obj


def unpack_array(obj: dict[Any, Any]) -> Any:
    if b"__ndarray__" in obj:
        return np.ndarray(buffer=obj[b"data"], dtype=np.dtype(obj[b"dtype"]), shape=obj[b"shape"])
    if b"__npgeneric__" in obj:
        return np.dtype(obj[b"dtype"]).type(obj[b"data"])
    return obj


Packer = functools.partial(msgpack.Packer, default=pack_array)
packb = functools.partial(msgpack.packb, default=pack_array)
unpackb = functools.partial(msgpack.unpackb, object_hook=unpack_array)


def _to_numpy(action: Any) -> np.ndarray:
    if hasattr(action, "detach"):
        action = action.detach().cpu().numpy()
    return np.asarray(action)


class WebsocketPolicyServer:
    """Serve a B1K policy over websocket (OmniGibson wire format)."""

    def __init__(
        self,
        policy: Any,
        host: str = "0.0.0.0",
        port: int = 8000,
        metadata: dict | None = None,
    ) -> None:
        self._policy = policy
        self._host = host
        self._port = port
        self._metadata = metadata or {}

    def serve_forever(self) -> None:
        asyncio.run(self.run())

    async def run(self) -> None:
        logger.info("Starting websocket server on %s:%d...", self._host, self._port)
        async with _server.serve(
            self._handler,
            self._host,
            self._port,
            compression=None,
            max_size=None,
            process_request=_health_check,
            ping_interval=60,
            ping_timeout=300,
        ) as server:
            await server.serve_forever()

    async def _handler(self, websocket: Any) -> None:
        logger.info("Connection from %s opened", websocket.remote_address)
        packer = Packer()
        await websocket.send(packer.pack(self._metadata))

        prev_total_time = None
        while True:
            try:
                start_time = time.monotonic()
                result = unpackb(await websocket.recv(), strict_map_key=False)
                if "reset" in result:
                    await asyncio.to_thread(self._policy.reset)
                    continue

                obs = deepcopy(result)
                infer_time = time.monotonic()
                action = await asyncio.to_thread(self._policy.act, obs)
                infer_time = time.monotonic() - infer_time

                payload = {
                    "action": _to_numpy(action),
                    "server_timing": {"infer_ms": infer_time * 1000},
                }
                if prev_total_time is not None:
                    payload["server_timing"]["prev_total_ms"] = prev_total_time * 1000

                await websocket.send(packer.pack(payload))
                prev_total_time = time.monotonic() - start_time
            except websockets.ConnectionClosed:
                logger.info("Connection from %s closed", websocket.remote_address)
                break
            except Exception:
                logger.error("Error in connection from %s:\n%s", websocket.remote_address, traceback.format_exc())
                try:
                    await websocket.close(
                        code=websockets.frames.CloseCode.INTERNAL_ERROR,
                        reason="Internal server error.",
                    )
                except AttributeError:
                    await websocket.close(code=1011, reason="Internal server error")
                break


def _health_check(connection: Any, request: Any) -> Optional[Any]:
    if hasattr(request, "path") and request.path == "/healthz":
        if hasattr(connection, "respond"):
            return connection.respond(http.HTTPStatus.OK, "OK\n")
        return http.HTTPStatus.OK, {"Content-Type": "text/plain"}, b"OK\n"
    return None
