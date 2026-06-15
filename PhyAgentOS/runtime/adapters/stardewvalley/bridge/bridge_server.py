"""HTTP API for the StarDojo bridge."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import mimetypes
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
    from PhyAgentOS.runtime.adapters.stardewvalley.bridge.action_parser import ActionParseError
    from PhyAgentOS.runtime.adapters.stardewvalley.bridge.benchmark_runtime import BenchmarkError, BenchmarkRuntime
    from PhyAgentOS.runtime.adapters.stardewvalley.bridge.stardew_runtime import StardewRuntime
else:
    from .action_parser import ActionParseError
    from .benchmark_runtime import BenchmarkError, BenchmarkRuntime
    from .stardew_runtime import StardewRuntime


def create_app(runtime: Any, benchmark_runtime: Any | None = None):
    """Create the Starlette app for a prepared runtime."""

    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import FileResponse, JSONResponse
    from starlette.routing import Route

    latest_image_path: Path | None = None
    benchmark_runtime = benchmark_runtime or BenchmarkRuntime(runtime)

    def image_url_for(request: Request) -> str:
        return str(request.url_for("latest_image"))

    def prepare_obs(obs: dict[str, Any], request: Request) -> dict[str, Any]:
        nonlocal latest_image_path
        obs = dict(obs)
        path = _runtime_latest_image_path(runtime)
        if path is not None:
            latest_image_path = path
            obs["latest_image_url"] = image_url_for(request)
        else:
            obs["latest_image_url"] = None
        return obs

    async def health(_request: Request) -> JSONResponse:
        stardojo_port = getattr(runtime, "stardojo_port", None)
        action_proxy = getattr(runtime, "env", None)
        action_proxy = getattr(action_proxy, "action_proxy", None)
        action_proxy_class = type(action_proxy) if action_proxy is not None else None
        return JSONResponse(
            {
                "ok": True,
                "stardojo_port": stardojo_port,
                "fast_recv": bool(getattr(action_proxy_class, "_phyagentos_fast_recv", False)),
                "action_proxy_class": str(action_proxy_class) if action_proxy_class is not None else None,
            }
        )

    async def observe(request: Request) -> JSONResponse:
        try:
            obs = await _call_runtime(runtime.observe)
            obs = prepare_obs(obs, request)
        except Exception as exc:
            return _error_response(exc, status_code=500)
        return JSONResponse({"ok": True, "obs": obs})

    async def execute(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            return _error_response("Request body must be JSON.", status_code=400)

        if not isinstance(payload, dict):
            return _error_response("Request body must be a JSON object.", status_code=400)

        action = payload.get("action")
        if not isinstance(action, str) or not action.strip():
            return _error_response("Missing non-empty string field: action", status_code=400)

        try:
            obs = await _call_runtime(runtime.execute, action)
            obs = prepare_obs(obs, request)
        except ActionParseError as exc:
            return _error_response(exc, status_code=400)
        except Exception as exc:
            return _error_response(exc, status_code=500)
        return JSONResponse({"ok": True, "action": action, "obs": obs})

    async def benchmark_start(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            return _error_response("Request body must be JSON.", status_code=400)

        if not isinstance(payload, dict):
            return _error_response("Request body must be a JSON object.", status_code=400)

        try:
            result = await _call_runtime(
                benchmark_runtime.start,
                payload.get("task_name"),
                payload.get("task_id"),
                payload.get("max_steps"),
            )
            obs = prepare_obs(result["obs"], request)
        except BenchmarkError as exc:
            return _error_response(exc, status_code=400)
        except Exception as exc:
            return _error_response(exc, status_code=500)
        return JSONResponse({"ok": True, "obs": obs, "benchmark": result["benchmark"]})

    async def benchmark_status(_request: Request) -> JSONResponse:
        try:
            benchmark = await _call_runtime(benchmark_runtime.status)
        except Exception as exc:
            return _error_response(exc, status_code=500)
        return JSONResponse({"ok": True, "benchmark": benchmark})

    async def benchmark_execute(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            return _error_response("Request body must be JSON.", status_code=400)

        if not isinstance(payload, dict):
            return _error_response("Request body must be a JSON object.", status_code=400)

        try:
            action = payload.get("action")
            result = await _call_runtime(benchmark_runtime.execute, action)
            obs = prepare_obs(result["obs"], request)
        except (ActionParseError, BenchmarkError) as exc:
            return _error_response(exc, status_code=400)
        except Exception as exc:
            return _error_response(exc, status_code=500)
        return JSONResponse({"ok": True, "action": action, "obs": obs, "benchmark": result["benchmark"]})

    async def benchmark_stop(_request: Request) -> JSONResponse:
        try:
            benchmark = await _call_runtime(benchmark_runtime.stop)
        except Exception as exc:
            return _error_response(exc, status_code=500)
        return JSONResponse({"ok": True, "benchmark": benchmark})

    async def latest_image(_request: Request):
        if latest_image_path is None or not latest_image_path.is_file():
            return _error_response("No screenshot is available yet. Call /observe first.", status_code=404)
        media_type = mimetypes.guess_type(str(latest_image_path))[0] or "application/octet-stream"
        return FileResponse(latest_image_path, media_type=media_type, filename=latest_image_path.name)

    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/observe", observe, methods=["GET"]),
            Route("/execute", execute, methods=["POST"]),
            Route("/benchmark/start", benchmark_start, methods=["POST"]),
            Route("/benchmark/status", benchmark_status, methods=["GET"]),
            Route("/benchmark/execute", benchmark_execute, methods=["POST"]),
            Route("/benchmark/stop", benchmark_stop, methods=["POST"]),
            Route("/images/latest", latest_image, methods=["GET"], name="latest_image"),
        ]
    )


def _runtime_latest_image_path(runtime: Any) -> Path | None:
    path = getattr(runtime, "latest_image_path", None)
    if path is None:
        return None
    path = Path(path).expanduser()
    if path.is_file():
        return path
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the PhyAgentOS StarDojo bridge.")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP bind host.")
    parser.add_argument("--port", type=int, default=8765, help="HTTP bind port.")
    parser.add_argument("--stardojo-port", type=int, default=10783, help="SMAPI Mod TCP port.")
    parser.add_argument(
        "--stardojo-root",
        default=None,
        help="Path to the StarDojo repo. Defaults to runtime/adapters/stardewvalley/stardojo.",
    )
    parser.add_argument(
        "--stardew-app-path",
        default=None,
        help="Optional path to StardewModdingAPI.exe. Usually not needed when the bridge attaches to an already-running SMAPI instance.",
    )
    parser.add_argument(
        "--image-save-path",
        default="screen_shot_buffer",
        help="Directory for StarDojo screenshot files. Use an empty string to disable.",
    )
    parser.add_argument(
        "--full-obs",
        action="store_true",
        help="Return full JSON-safe StarDojo observations instead of compact observations.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    image_save_path = args.image_save_path or None
    runtime = StardewRuntime(
        stardojo_port=args.stardojo_port,
        stardojo_root=args.stardojo_root,
        stardew_app_path=args.stardew_app_path,
        image_save_path=image_save_path,
        compact=not args.full_obs,
    )
    app = create_app(runtime)

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


async def _call_runtime(func, *args):
    result = await asyncio.to_thread(func, *args)
    if inspect.isawaitable(result):
        return await result
    return result


def _error_response(error: Any, *, status_code: int):
    from starlette.responses import JSONResponse

    message = str(error)
    return JSONResponse({"ok": False, "error": message}, status_code=status_code)


if __name__ == "__main__":
    main()

