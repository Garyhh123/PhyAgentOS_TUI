"""Agent-owned HTTP service for scoped benchmark episode verification."""

from __future__ import annotations

import asyncio
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
import hmac
import os
import subprocess
import sys
import threading
import time
from typing import Any

import numpy as np

from PhyAgentOS.verification.engine import VerificationEngine
from PhyAgentOS.runtime.artifacts.episode_writer import _encode_rgb_png


EPISODE_PROMPT = """You are a benchmark episode verifier. Return one JSON object with keys verdict
(success|replan|failure), evidence, failure_reason, replan_task_description, and lesson.
Compare the initial and final observations. Use replan only when a rewritten instruction can recover the task."""


class VerificationServiceProcess:
    def __init__(self, *, engine: VerificationEngine, host: str, port: int, episode_token: str, provider_spec: dict | None = None) -> None:
        self.engine = engine
        self.host = host
        self.port = int(port)
        self.episode_token = episode_token
        self.session_token = hashlib.sha256((episode_token + ":session").encode()).hexdigest()
        self.provider_spec = provider_spec
        self._process: subprocess.Popen | None = None
        self._lifecycle_lock = threading.Lock()
        self._closed = False

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                return
            if self._process is not None and self._process.poll() is None:
                return
            if self.provider_spec is None:
                raise RuntimeError("Verification Service requires a serializable provider specification")
            settings = {
                "provider": self.provider_spec, "host": self.host, "port": self.port,
                "episode_token": self.episode_token, "session_token": self.session_token,
                "timeout_s": self.engine.timeout_s,
            }
            env = dict(os.environ)
            env["PAOS_VERIFICATION_SERVICE_CONFIG"] = json.dumps(settings)
            self._process = subprocess.Popen(
                [sys.executable, "-m", "PhyAgentOS.verification.service"],
                env=env,
                stdin=subprocess.DEVNULL,
            )
        deadline = time.monotonic() + 5.0
        from urllib import request
        opener = request.build_opener(request.ProxyHandler({}))
        probe_host = "127.0.0.1" if self.host == "0.0.0.0" else self.host
        while time.monotonic() < deadline:
            with self._lifecycle_lock:
                if self._closed:
                    return
                process = self._process
            if process is None or process.poll() is not None:
                raise RuntimeError("Verification Service exited before readiness")
            try:
                with opener.open(f"http://{probe_host}:{self.port}/healthz", timeout=0.2) as response:  # noqa: S310
                    if response.status == 200:
                        return
            except OSError:
                time.sleep(0.05)
        self.stop()
        raise TimeoutError("Verification Service readiness timed out")

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._closed = True
            process = self._process
            self._process = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)


def serve_verification_service(engine: VerificationEngine, host: str, port: int, episode_token: str, session_token: str) -> None:
    server = ThreadingHTTPServer((host, port), _handler(engine, episode_token, session_token))
    server.serve_forever(poll_interval=0.2)


def _handler(engine: VerificationEngine, episode_token: str, session_token: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self._send({"ok": self.path == "/healthz"}, 200 if self.path == "/healthz" else 404)

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/v1/verify-episode":
                self._verify_episode()
                return
            if self.path == "/v1/verify-session":
                if self.headers.get("X-PAOS-Admin-Token") != session_token:
                    self._send({"error": "session verification is restricted to the Agent wrapper"}, 403)
                    return
                self._verify_session()
                return
            self._send({"error": "not found"}, 404)

        def _verify_episode(self) -> None:
            try:
                bundle = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                if bundle.get("version") != "benchmark_episode_verification_v1":
                    raise ValueError("unsupported episode verification bundle")
                token = str(self.headers.get("Authorization") or "").removeprefix("Bearer ")
                if not _valid_episode_token(token, episode_token, bundle):
                    self._send({"error": "invalid or expired episode verification token"}, 403)
                    return
                data = asyncio.run(engine.complete(system_prompt=EPISODE_PROMPT, content=_episode_content(bundle)))
                self._send(_normalize(data), 200)
            except Exception as exc:  # noqa: BLE001
                self._send({"verdict": "failure", "evidence": [str(exc)], "failure_reason": str(exc), "replan_task_description": None, "lesson": "Verification failed.", "verifier_status": "error"}, 500)

        def _verify_session(self) -> None:
            try:
                bundle = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                if bundle.get("version") != "agent_session_verification_v2" or not isinstance(bundle.get("content"), list):
                    raise ValueError("unsupported session verification bundle")
                data = asyncio.run(engine.complete(system_prompt="Verify the Agent session and return a semantic verdict JSON object.", content=bundle["content"]))
                self._send(_normalize(data), 200)
            except Exception as exc:  # noqa: BLE001
                self._send({"verdict": "failure", "evidence": [str(exc)], "failure_reason": str(exc), "replan_task_description": None, "lesson": "Verification failed.", "verifier_status": "error"}, 500)

        def _send(self, payload: dict, status: int) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def _episode_content(bundle: dict) -> list[dict]:
    context = {key: value for key, value in bundle.items() if key not in {"initial_observation", "final_observation"}}
    content: list[dict] = [{"type": "text", "text": json.dumps(context, ensure_ascii=False)}]
    for phase in ("initial_observation", "final_observation"):
        for name, image in _rgb_arrays(bundle.get(phase), phase):
            png = _encode_rgb_png(image)
            content.extend([{"type": "text", "text": name}, {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}])
    return content


def _rgb_arrays(value: Any, prefix: str) -> list[tuple[str, np.ndarray]]:
    found: list[tuple[str, np.ndarray]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            found.extend(_rgb_arrays(item, prefix + "." + str(key)))
        return found
    try:
        array = np.asarray(value, dtype=np.uint8)
    except Exception:
        return found
    if array.ndim == 3 and array.shape[-1] == 3:
        found.append((prefix, np.ascontiguousarray(array)))
    return found


def _normalize(data: dict) -> dict:
    verdict = str(data.get("verdict") or "failure")
    if verdict not in {"success", "replan", "failure"}:
        verdict = "failure"
    rewrite = str(data.get("replan_task_description") or "").strip()
    status = "completed"
    reason = data.get("failure_reason")
    if verdict == "replan" and not rewrite:
        verdict, status, reason = "failure", "invalid_response", "replan requires non-empty replan_task_description"
    return {"verdict": verdict, "evidence": [str(item) for item in (data.get("evidence") or ["no evidence"])], "failure_reason": reason, "replan_task_description": rewrite or None, "lesson": str(data.get("lesson") or "No lesson provided."), "verifier_status": status}


def _valid_episode_token(token: str, secret: str, bundle: dict) -> bool:
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return False
        padded = encoded + "=" * (-len(encoded) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        return (
            int(claims["expires_at"]) >= int(time.time())
            and str(claims["run_id"]) == str(bundle.get("run_id"))
            and str(claims["session_id"]) == str(bundle.get("session_id"))
        )
    except Exception:
        return False


def _provider(spec: dict):
    from PhyAgentOS.providers.base import GenerationSettings

    name = str(spec["provider_name"])
    model = str(spec["model"])
    if name == "custom":
        from PhyAgentOS.providers.custom_provider import CustomProvider
        provider = CustomProvider(api_key=spec.get("api_key") or "no-key", api_base=spec.get("api_base") or "http://localhost:8000/v1", default_model=model)
    elif name == "azure_openai":
        from PhyAgentOS.providers.azure_openai_provider import AzureOpenAIProvider
        provider = AzureOpenAIProvider(api_key=spec.get("api_key"), api_base=spec.get("api_base"), default_model=model)
    elif name == "openai_codex":
        from PhyAgentOS.providers.openai_codex_provider import OpenAICodexProvider
        provider = OpenAICodexProvider(default_model=model)
    else:
        from PhyAgentOS.providers.litellm_provider import LiteLLMProvider
        provider = LiteLLMProvider(api_key=spec.get("api_key"), api_base=spec.get("api_base"), default_model=model, extra_headers=spec.get("extra_headers"), provider_name=name)
    provider.generation = GenerationSettings(temperature=float(spec.get("temperature", 0.0)), max_tokens=int(spec.get("max_tokens", 1024)), reasoning_effort=spec.get("reasoning_effort"))
    return provider


def main() -> int:
    settings = json.loads(os.environ["PAOS_VERIFICATION_SERVICE_CONFIG"])
    provider = _provider(settings["provider"])
    engine = VerificationEngine(provider=provider, model=settings["provider"]["model"], timeout_s=float(settings["timeout_s"]))
    serve_verification_service(engine, settings["host"], int(settings["port"]), settings["episode_token"], settings["session_token"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
