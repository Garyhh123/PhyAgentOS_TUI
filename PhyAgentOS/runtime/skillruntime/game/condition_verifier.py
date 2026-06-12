"""Game condition verification primitives.

Each game implements its own ConditionVerifier subclass to check
preconditions and post-conditions against the current observation
and target state.

The TaskPlan schema's verify fields use string descriptors like
"has_item:diamond" or "npc_near:Wizard,5" — each game's verifier
parses its own descriptor format.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class GameConditionVerifier(ABC):
    """Abstract verifier: checks TaskPlan condition descriptors.

    Each game target provides its own implementation that understands
    that game's descriptor format.
    """

    def __init__(self, target, raw_obs: dict[str, Any]):
        self._target = target
        self._obs = raw_obs

    @abstractmethod
    def verify(self, descriptor: str) -> bool:
        """Verify a single descriptor. Returns True if condition holds."""

    def verify_all(self, descriptors: list[str]) -> tuple[bool, list[str]]:
        """Verify a list of descriptors. Returns (all_ok, failures)."""
        failures = []
        for d in descriptors:
            if not self.verify(d):
                failures.append(d)
        return len(failures) == 0, failures
