"""Episode-level verifier client for target-native benchmark assistance."""

from __future__ import annotations

import json
from typing import Any
from urllib import error, request


class BenchmarkEpisodeVerifier:
    """Call an external Agent verifier for one benchmark episode attempt.

    Runtime owns benchmark orchestration, but it should not import an Agent loop
    or LLM provider directly. This client keeps the boundary explicit: an
    Agent-side service can expose an HTTP endpoint that accepts an evidence
    bundle and returns a verdict.
    """

    def __init__(
        self,
        *,
        endpoint: str | None,
        timeout_s: float = 60.0,
        failure_policy: str = "skip",
    ) -> None:
        self.endpoint = endpoint
        self.timeout_s = float(timeout_s)
        self.failure_policy = str(failure_policy or "skip")

    def verify(self, bundle: dict[str, Any]) -> dict[str, Any]:
        if not self.endpoint:
            return self._fallback("verifier endpoint is not configured")
        if self.endpoint.startswith("mock://"):
            return self._mock_verdict(bundle)
        if not self.endpoint.startswith(("http://", "https://")):
            return self._fallback(f"unsupported verifier endpoint: {self.endpoint}")
        try:
            payload = json.dumps(_jsonable(bundle), ensure_ascii=False).encode("utf-8")
            req = request.Request(
                self.endpoint,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310 - user-configured endpoint
                data = json.loads(resp.read().decode("utf-8"))
        except (OSError, TimeoutError, error.URLError, json.JSONDecodeError) as exc:
            return self._fallback(str(exc))
        return _normalize_verdict(data)

    def _mock_verdict(self, bundle: dict[str, Any]) -> dict[str, Any]:
        mode = self.endpoint.removeprefix("mock://")
        if mode in {"replan", "replan_failed"}:
            return {
                "verdict": "replan",
                "evidence": ["mock verifier requested a retry for this failed attempt"],
                "failure_reason": None,
                "replan_task_description": bundle.get("task_description"),
                "lesson": "Mock verifier retries failed benchmark episodes.",
                "verifier_status": "mock",
            }
        if mode == "success":
            return {
                "verdict": "success",
                "evidence": ["mock verifier accepted the attempt"],
                "failure_reason": None,
                "replan_task_description": None,
                "lesson": "Mock verifier accepted the attempt.",
                "verifier_status": "mock",
            }
        return self._fallback(f"unsupported mock verifier mode: {mode}")

    def _fallback(self, reason: str) -> dict[str, Any]:
        if self.failure_policy == "retry":
            return {
                "verdict": "replan",
                "evidence": [f"verifier unavailable; failure_policy=retry: {reason}"],
                "failure_reason": None,
                "replan_task_description": None,
                "lesson": "Retry was selected by verifier failure policy.",
                "verifier_status": "fallback_retry",
            }
        if self.failure_policy == "failure":
            return {
                "verdict": "failure",
                "evidence": [f"verifier unavailable; failure_policy=failure: {reason}"],
                "failure_reason": reason,
                "replan_task_description": None,
                "lesson": "Episode remained failed because verifier was unavailable.",
                "verifier_status": "fallback_failure",
            }
        return {
            "verdict": "skipped",
            "evidence": [f"verifier skipped: {reason}"],
            "failure_reason": reason,
            "replan_task_description": None,
            "lesson": "Episode verification was skipped.",
            "verifier_status": "skipped",
        }


def _normalize_verdict(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("verifier response must be a JSON object")
    verdict = str(data.get("verdict") or "failure")
    if verdict not in {"success", "replan", "failure", "skipped"}:
        verdict = "failure"
    evidence = data.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        evidence = ["verifier did not provide evidence"]
    return {
        "verdict": verdict,
        "evidence": [str(item) for item in evidence],
        "failure_reason": data.get("failure_reason"),
        "replan_task_description": data.get("replan_task_description"),
        "lesson": str(data.get("lesson") or "No verifier lesson was provided."),
        "verifier_status": str(data.get("verifier_status") or "completed"),
        "details": data,
    }


def _jsonable(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
