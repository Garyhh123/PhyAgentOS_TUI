"""Gentle demo motion for BEHAVIOR-1K ``dummy_baseline`` benchmark runs.

Standalone module: only ``torch`` + stdlib so behavior conda (Python 3.10)
can import it without pulling in PhyAgentOS runtime schemas (StrEnum/py3.11).
"""

from __future__ import annotations

import math
from typing import Any, Optional

import torch as th

_SLICE_BASE = slice(0, 3)
_SLICE_TORSO = slice(3, 7)
_SLICE_LEFT_ARM = slice(7, 14)
_SLICE_LEFT_GRIPPER = 14
_SLICE_RIGHT_ARM = slice(15, 22)
_SLICE_RIGHT_GRIPPER = 22


class DemoWigglePolicy:
    """Hydra-compatible policy with the same surface as ``LocalPolicy``."""

    def __init__(self, *args: Any, action_dim: Optional[int] = None, **kwargs: Any) -> None:
        self.policy = None
        self.action_dim = int(action_dim or 23)
        self._step = 0

    def reset(self) -> None:
        self._step = 0

    def act(self, obs: dict) -> th.Tensor:
        return self.forward(obs)

    def forward(self, obs: dict, *args: Any, **kwargs: Any) -> th.Tensor:
        del obs, args, kwargs
        if self.policy is not None:
            return self.policy.act(obs).detach().cpu()

        t = self._step * 0.04
        self._step += 1
        action = th.zeros(self.action_dim, dtype=th.float32)

        action[_SLICE_BASE] = th.tensor(
            [
                0.06 * math.sin(t * 0.8),
                0.04 * math.sin(t * 0.6 + 0.5),
                0.05 * math.sin(t * 0.5 + 1.0),
            ],
            dtype=th.float32,
        )
        action[_SLICE_TORSO] = th.tensor(
            [0.035 * math.sin(t + i * 0.7) for i in range(4)],
            dtype=th.float32,
        )
        action[_SLICE_LEFT_ARM] = th.tensor(
            [0.05 * math.sin(t * 0.9 + i * 0.55) for i in range(7)],
            dtype=th.float32,
        )
        action[_SLICE_RIGHT_ARM] = th.tensor(
            [0.10 * math.sin(t * 1.2 + i * 0.65) for i in range(7)],
            dtype=th.float32,
        )
        action[_SLICE_LEFT_GRIPPER] = 0.25 * math.sin(t * 1.6)
        action[_SLICE_RIGHT_GRIPPER] = 0.35 * math.sin(t * 1.8 + 0.3)
        return action
