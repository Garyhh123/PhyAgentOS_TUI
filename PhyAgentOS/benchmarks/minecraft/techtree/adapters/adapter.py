"""Thin HTTP adapter for a mineflayer bridge.

World-setup logic (arena isolation, inventory reset, item grants with
enchantment NBT, relative block placement, phase tracking) lives in the
bridge itself under ``POST /benchmark/reset``.  This adapter is only a
forwarder: it implements the benchmark :class:`WorldAdapter` interface
(``reset(setup)`` / ``observe()``) by delegating to those bridge
endpoints.

The adapter is intentionally outside the benchmark core.  Users may
provide their own adapter as long as it implements ``reset(setup)`` and
``observe()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import httpx

from PhyAgentOS.benchmarks.minecraft.techtree.schema import WorldSetup


@dataclass
class MineflayerBridgeAdapter:
    bridge_url: str = "http://127.0.0.1:3000"
    timeout_s: float = 60.0
    verify_ssl: bool = False

    def reset(self, setup: WorldSetup) -> Mapping[str, Any]:
        """Reset the world for one benchmark task.

        The whole :class:`WorldSetup` is serialized and POSTed to the
        bridge's ``/benchmark/reset`` endpoint, which runs arena
        isolation, clears the inventory, grants setup items, and places
        task blocks server-side.  Returns the post-reset observation.
        """

        self._set_phase("reset", reset_counters=True)
        try:
            self._post("/benchmark/reset", setup.to_dict())
            return self.observe()
        finally:
            self._set_phase("idle", reset_counters=False)

    def observe(self) -> Mapping[str, Any]:
        return self._get("/state")

    def execute_action(self, action: str, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        """Forward a single bridge action (``{type, params}`` payload)."""

        return self._post(
            "/action",
            {"type": action, "params": dict(params or {})},
        )

    # ── HTTP plumbing ────────────────────────────────────────────────
    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.timeout_s,
            verify=self.verify_ssl,
            trust_env=False,
            headers={"ngrok-skip-browser-warning": "true"},
        )

    def _get(self, path: str) -> dict[str, Any]:
        with self._client() as client:
            response = client.get(f"{self.bridge_url.rstrip('/')}{path}")
            response.raise_for_status()
            return response.json()

    def _post(self, path: str, body: Mapping[str, Any]) -> dict[str, Any]:
        with self._client() as client:
            response = client.post(
                f"{self.bridge_url.rstrip('/')}{path}",
                json=dict(body),
            )
            response.raise_for_status()
            return response.json()

    def _set_phase(self, phase: str, *, reset_counters: bool) -> Mapping[str, Any]:
        try:
            return self._post(
                "/phase",
                {
                    "phase": phase,
                    "reset_counters": reset_counters,
                    "source": "minecraft_techtree",
                },
            )
        except httpx.HTTPError:
            # Phase is advisory; a bridge without the endpoint must not
            # break a reset.  The benchmark reset endpoint sets phase
            # internally regardless.
            return {"ok": False, "phase": phase}
