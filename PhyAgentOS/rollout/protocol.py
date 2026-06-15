"""WebSocket rollout protocol: msgpack envelopes with optional ndarray payloads."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import msgpack
import numpy as np

_NDARRAY_TAG = "__ndarray__"


def _pack_ndarray(arr: np.ndarray) -> dict[str, Any]:
    return {
        _NDARRAY_TAG: True,
        "dtype": str(arr.dtype),
        "shape": list(arr.shape),
        "data": arr.tobytes(),
    }


def _unpack_ndarray(obj: dict[str, Any]) -> np.ndarray:
    return np.frombuffer(obj["data"], dtype=np.dtype(obj["dtype"])).reshape(obj["shape"])


def _pack_obj(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return _pack_ndarray(value)
    if isinstance(value, dict):
        return {str(k): _pack_obj(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_pack_obj(v) for v in value]
    return value


def _unpack_obj(value: Any) -> Any:
    if isinstance(value, dict):
        if value.get(_NDARRAY_TAG) is True:
            return _unpack_ndarray(value)
        return {k: _unpack_obj(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_unpack_obj(v) for v in value]
    return value


def encode_message(obj: dict[str, Any]) -> bytes:
    return msgpack.packb(_pack_obj(obj), use_bin_type=True)


def decode_message(data: bytes) -> dict[str, Any]:
    raw = msgpack.unpackb(data, raw=False)
    if not isinstance(raw, dict):
        raise ValueError("rollout message must be a dict")
    return _unpack_obj(raw)


@dataclass
class RolloutRequest:
    type: str
    session_id: str = ""
    episode_id: str = ""
    seq: int = 0
    timestamp: float = field(default_factory=time.time)
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RolloutRequest:
        return cls(
            type=str(data.get("type", "")).strip(),
            session_id=str(data.get("session_id", "")),
            episode_id=str(data.get("episode_id", "")),
            seq=int(data.get("seq", 0)),
            timestamp=float(data.get("timestamp", time.time())),
            payload=dict(data.get("payload") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "session_id": self.session_id,
            "episode_id": self.episode_id,
            "seq": self.seq,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }


@dataclass
class RolloutResponse:
    type: str
    ok: bool
    session_id: str = ""
    episode_id: str = ""
    seq: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "ok": self.ok,
            "session_id": self.session_id,
            "episode_id": self.episode_id,
            "seq": self.seq,
            "payload": self.payload,
            "error": self.error,
        }

    @classmethod
    def from_request(
        cls,
        request: RolloutRequest,
        *,
        ok: bool,
        payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> RolloutResponse:
        return cls(
            type=request.type,
            ok=ok,
            session_id=request.session_id,
            episode_id=request.episode_id,
            seq=request.seq,
            payload=dict(payload or {}),
            error=error,
        )
