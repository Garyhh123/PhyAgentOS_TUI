#!/usr/bin/env python
"""Run an HTTP verifier service for target-native benchmark episodes."""

from __future__ import annotations

import argparse
import asyncio
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import struct
import sys
from typing import Any
import zlib

import json_repair
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PhyAgentOS.providers.custom_provider import CustomProvider


SYSTEM_PROMPT = """You are a benchmark episode verifier for robot manipulation.
Return exactly one JSON object. Do not include markdown.

Allowed verdict values:
- success: the episode appears semantically complete despite a target failure signal.
- replan: another attempt of the same task is worth running.
- failure: retry is unlikely to help or evidence is too weak.

Required JSON keys:
verdict, evidence, failure_reason, replan_task_description, lesson.

Use the task, runtime claim, initial observation images, and final observation
images. First compare the initial state against the final state, then decide
whether the task is complete or a retry is useful. Prefer replan for potentially
recoverable manipulation failures.
"""


class VerifierService:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_s: float,
        max_tokens: int,
        temperature: float,
    ) -> None:
        self.provider = CustomProvider(api_key=api_key, api_base=base_url, default_model=model)
        self.model = model
        self.timeout_s = float(timeout_s)
        self.max_tokens = int(max_tokens)
        self.temperature = float(temperature)

    async def verify(self, bundle: dict[str, Any]) -> dict[str, Any]:
        evidence_bundle = _verifier_context(bundle)
        content = _multimodal_content(evidence_bundle, bundle)
        response = await asyncio.wait_for(
            self.provider.chat_with_retry(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
                tools=None,
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            ),
            timeout=self.timeout_s,
        )
        if response.finish_reason == "error" or not response.content:
            raise RuntimeError(response.content or "verifier model returned no content")
        return _normalize_verdict(json_repair.loads(response.content))


def make_handler(service: VerifierService):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PhyAgentOSBenchmarkVerifier/1.0"

        def do_GET(self) -> None:  # noqa: N802
            if self.path in {"/health", "/healthz"}:
                self._send_json({"ok": True, "model": service.model})
                return
            self._send_json({"ok": False, "error": "not found"}, status=404)

        def do_POST(self) -> None:  # noqa: N802
            if self.path.rstrip("/") != "/verify_benchmark_episode":
                self._send_json({"ok": False, "error": "not found"}, status=404)
                return
            try:
                length = int(self.headers.get("Content-Length") or "0")
                raw = self.rfile.read(length)
                bundle = json.loads(raw.decode("utf-8"))
                verdict = asyncio.run(service.verify(bundle))
                self._send_json(verdict)
            except Exception as exc:  # noqa: BLE001
                self._send_json(
                    {
                        "verdict": "failure",
                        "evidence": [f"verifier service error: {exc}"],
                        "failure_reason": str(exc),
                        "replan_task_description": None,
                        "lesson": "Verifier service failed to produce a valid verdict.",
                        "verifier_status": "error",
                    },
                    status=500,
                )

        def log_message(self, fmt: str, *args: Any) -> None:
            print("[benchmark-verifier] " + fmt % args, flush=True)

        def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _verifier_context(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": bundle.get("version"),
        "run_id": bundle.get("run_id"),
        "suite_id": bundle.get("suite_id"),
        "episode_id": bundle.get("episode_id"),
        "task_index": bundle.get("task_index"),
        "instance_id": bundle.get("instance_id"),
        "attempt_index": bundle.get("attempt_index"),
        "task_description": bundle.get("task_description"),
        "runtime_claim": bundle.get("runtime_claim"),
        "final_status": bundle.get("final_status"),
        "initial_observation_summary": _observation_summary(bundle.get("initial_observation")),
        "final_observation_summary": _observation_summary(bundle.get("final_observation")),
    }


def _multimodal_content(context: dict[str, Any], bundle: dict[str, Any]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Verify this benchmark episode attempt. Compare initial images "
                "with final images before choosing a verdict.\n\n"
                f"{json.dumps(context, ensure_ascii=False, indent=2)}"
            ),
        }
    ]
    content.extend(_observation_image_blocks("initial", bundle.get("initial_observation")))
    content.extend(_observation_image_blocks("final", bundle.get("final_observation")))
    return content


def _observation_image_blocks(phase: str, obs: Any) -> list[dict[str, Any]]:
    if not isinstance(obs, dict):
        return []
    blocks: list[dict[str, Any]] = []
    for name, value in obs.items():
        if not _looks_like_rgb_key(name):
            continue
        png = _png_from_json_array(value)
        if png is None:
            continue
        blocks.append({"type": "text", "text": f"{phase} observation: {name}"})
        blocks.append(
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")},
            }
        )
    return blocks


def _looks_like_rgb_key(name: str) -> bool:
    lowered = str(name).lower()
    return "image" in lowered or "rgb" in lowered


def _png_from_json_array(value: Any) -> bytes | None:
    try:
        array = np.asarray(value, dtype=np.uint8)
    except Exception:
        return None
    if array.ndim != 3:
        return None
    if array.shape[-1] == 3:
        rgb = array
    elif array.shape[0] == 3:
        rgb = np.transpose(array, (1, 2, 0))
    else:
        return None
    return _encode_rgb_png(np.ascontiguousarray(rgb))


def _observation_summary(obs: Any) -> Any:
    if not isinstance(obs, dict):
        return None
    summary: dict[str, Any] = {}
    for key, value in obs.items():
        if hasattr(value, "shape") and hasattr(value, "dtype"):
            summary[key] = {"shape": list(value.shape), "dtype": str(value.dtype)}
        elif isinstance(value, list):
            summary[key] = {"type": "list", "length": len(value), "sample": value[:8]}
        elif isinstance(value, int | float | str | bool) or value is None:
            summary[key] = value
        else:
            summary[key] = str(type(value).__name__)
    return summary


def _normalize_verdict(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("model output is not a JSON object")
    verdict = str(data.get("verdict") or "failure")
    if verdict not in {"success", "replan", "failure"}:
        verdict = "failure"
    evidence = data.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        evidence = ["model did not provide evidence"]
    return {
        "verdict": verdict,
        "evidence": [str(item) for item in evidence],
        "failure_reason": data.get("failure_reason"),
        "replan_task_description": data.get("replan_task_description"),
        "lesson": str(data.get("lesson") or "No lesson provided."),
        "verifier_status": "completed",
    }


def _encode_rgb_png(array: np.ndarray) -> bytes:
    height, width, channels = array.shape
    if channels != 3:
        raise ValueError(f"RGB frame must have three channels, got {array.shape}")
    raw = b"".join(b"\x00" + array[row].tobytes() for row in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    signature = b"\x89PNG\r\n\x1a\n"
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return signature + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--base-url", default="https://www.dmxapi.cn/v1")
    parser.add_argument("--model", default="qwen3.5-flash")
    parser.add_argument("--api-key-env", default="DMXAPI_API_KEY")
    parser.add_argument("--timeout-s", type=float, default=90)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.0)
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env) or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        parser.error(f"set {args.api_key_env} or OPENAI_API_KEY")
    service = VerifierService(
        api_key=api_key,
        base_url=args.base_url,
        model=args.model,
        timeout_s=args.timeout_s,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service))
    print(
        "[benchmark-verifier] serving http://%s:%d/verify_benchmark_episode model=%s base_url=%s"
        % (args.host, args.port, args.model, args.base_url),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[benchmark-verifier] stopping", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
