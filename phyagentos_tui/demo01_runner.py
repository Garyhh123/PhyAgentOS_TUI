"""Demo 01 runner for the TUI on the current AgentTask + Tool API core."""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import re
import struct
import time
import zlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

import PhyAgentOS.forge.task as forge_task_module
from PhyAgentOS.config.schema import ForgeConfig, ForgeEvidenceConfig
from PhyAgentOS.forge.observation import ForgeObservationCollector
from PhyAgentOS.forge.task import AgentTaskCoordinator, AgentTaskRecord
from PhyAgentOS.forge.tool_client import ForgeToolClient
from PhyAgentOS.verification.contracts import (
    CriterionVerdict,
    TaskVerificationContract,
    VerificationAttempt,
    VerificationEvidencePolicy,
    VerificationVerdict,
)


EventSink = Callable[[dict[str, Any]], Awaitable[None] | None]

CAMERA_SOURCE = "top_camera"
DEMO_BASE_URL = "http://127.0.0.1:19002"
MOVE_DURATION_S = 2.2
GRIPPER_DURATION_S = 1.5

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "tool_id": "motion.resolve_relative_pose",
        "implementation_id": "motion.integration",
        "endpoint_id": "motion.relative_pose",
        "operation": "resolve",
        "semantics": "query",
        "description": "Resolve a relative TCP delta into an absolute target pose.",
        "robot_frame_profile": {
            "robot_id": "piper",
            "base_frame": "arm_base",
            "tool_frame": "tcp",
        },
    },
    {
        "tool_id": "motion.move_pose",
        "implementation_id": "motion.integration",
        "endpoint_id": "motion.server",
        "operation": "move_pose",
        "semantics": "action",
        "description": "Move the robot TCP to a target pose.",
        "robot_frame_profile": {
            "robot_id": "piper",
            "base_frame": "arm_base",
            "tool_frame": "tcp",
        },
    },
    {
        "tool_id": "gripper.set_opening",
        "implementation_id": "piper.gripper",
        "endpoint_id": "gripper.controller",
        "operation": "set_opening",
        "semantics": "action",
        "description": "Set the gripper opening in meters.",
        "robot_frame_profile": {
            "robot_id": "piper",
            "base_frame": "arm_base",
            "tool_frame": "tcp",
        },
    },
]


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def _encode_png(width: int, height: int, robot: "DemoRobot") -> bytes:
    z_ratio = max(0.0, min(1.0, (robot.tcp_pose["z"] - 0.15) / 0.15))
    g_ratio = max(0.0, min(1.0, robot.gripper_opening_m / 0.105))
    column_height = int(height * 0.75 * z_ratio)
    bar_width = int(width * 0.8 * g_ratio)
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            if x < 24 and y >= height - 8 - column_height:
                pixel = (64, 200, 96)
            elif 30 <= x < 30 + bar_width and y >= height - 6:
                pixel = (64, 190, 220)
            else:
                shade = 28 + int(24 * z_ratio)
                pixel = (shade, shade, shade + 6)
            raw.extend(pixel)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _png_chunk(b"IEND", b"")
    )


class DemoRobot:
    """Small deterministic robot world used by the in-app demo."""

    def __init__(self) -> None:
        self.tcp_pose = {
            "x": 0.320,
            "y": 0.000,
            "z": 0.210,
            "qx": 0.0,
            "qy": 0.0,
            "qz": 0.0,
            "qw": 1.0,
        }
        self.gripper_opening_m = 0.0
        self.joint_positions = [0.12, -0.35, 0.62, 0.0, 0.41, -0.08]
        self.state_version = 1
        self.invocations: dict[str, dict[str, Any]] = {}

    def start_action(self, tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        record = {
            "invocation_id": f"inv_{uuid4().hex[:12]}",
            "attempt_id": f"att_{uuid4().hex[:12]}",
            "goal_id": f"goal_{uuid4().hex[:12]}",
            "tool_id": tool_id,
            "arguments": dict(arguments),
            "started_mono": time.monotonic(),
            "duration": MOVE_DURATION_S if tool_id == "motion.move_pose" else GRIPPER_DURATION_S,
            "applied": False,
            "initial_pose": dict(self.tcp_pose),
            "initial_gripper": self.gripper_opening_m,
        }
        self.invocations[record["invocation_id"]] = record
        return record

    def phase_of(self, record: dict[str, Any]) -> str:
        elapsed = time.monotonic() - float(record["started_mono"])
        if elapsed < 0.35:
            return "accepted"
        if elapsed < float(record["duration"]):
            self._apply_progress(record, elapsed / float(record["duration"]))
            return "running"
        self._apply_progress(record, 1.0)
        return "completed"

    def sync(self) -> None:
        for record in list(self.invocations.values()):
            self.phase_of(record)

    def _apply_progress(self, record: dict[str, Any], progress: float) -> None:
        progress = max(0.0, min(1.0, progress))
        before = (self.tcp_pose["z"], self.gripper_opening_m)
        if record["tool_id"] == "motion.move_pose":
            target = record["arguments"]["target_pose"]
            initial = record["initial_pose"]
            self.tcp_pose.update(
                {
                    key: round(
                        float(initial[key])
                        + (float(target[key]) - float(initial[key])) * progress,
                        4,
                    )
                    for key in ("x", "y", "z", "qx", "qy", "qz", "qw")
                }
            )
            if progress >= 1.0 and not record["applied"]:
                self.joint_positions = [round(value + 0.03, 4) for value in self.joint_positions]
                record["applied"] = True
        elif record["tool_id"] == "gripper.set_opening":
            target = float(record["arguments"]["opening_m"]) + 0.0008
            initial = float(record["initial_gripper"])
            self.gripper_opening_m = round(initial + (target - initial) * progress, 4)
            if progress >= 1.0:
                record["applied"] = True
        if before != (self.tcp_pose["z"], self.gripper_opening_m):
            self.state_version += 1

    def result_of(self, record: dict[str, Any]) -> dict[str, Any]:
        self._apply_progress(record, 1.0)
        if record["tool_id"] == "motion.move_pose":
            return {
                "status": "succeeded",
                "goal_id": record["goal_id"],
                "motion_result": {
                    "error_code": "SUCCESS",
                    "message": "goal reached within tolerance",
                    "elapsed_ns": int(float(record["duration"]) * 1e9),
                    "final_pose": dict(self.tcp_pose),
                    "final_position_error_m": 0.0004,
                    "final_orientation_error_rad": 0.0011,
                    "final_joint_positions": list(self.joint_positions),
                },
            }
        return {
            "status": "succeeded",
            "goal_id": record["goal_id"],
            "gripper_result": {
                "error_code": "SUCCESS",
                "message": "opening reached",
                "elapsed_ns": int(float(record["duration"]) * 1e9),
                "position": round(self.gripper_opening_m, 4),
                "velocity": 0.0,
                "effort": None,
                "stalled": False,
                "reached_goal": True,
            },
        }

    def state(self) -> dict[str, Any]:
        self.sync()
        return {
            "robot_id": "piper-sim",
            "state_version": self.state_version,
            "tcp_pose": dict(self.tcp_pose),
            "gripper": {"opening_m": round(self.gripper_opening_m, 4)},
            "gripper_opening_m": round(self.gripper_opening_m, 4),
            "joint_positions": list(self.joint_positions),
            "timestamp": time.time(),
        }


class DemoWebSocket:
    def __init__(self, feed: "DemoObservationFeed", path: str) -> None:
        self.feed = feed
        self.path = path
        self._queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=8)
        self._closed = False

    async def recv(self) -> str | None:
        return await self._queue.get()

    def close(self) -> None:
        self._closed = True
        self.feed.unregister(self)
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

    def push(self, message: str) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            pass


class DemoObservationFeed:
    def __init__(self, robot: DemoRobot) -> None:
        self.robot = robot
        self._connections: set[DemoWebSocket] = set()
        self._task: asyncio.Task[None] | None = None
        self._sequence = 0

    def connection_factory(self, url: str, timeout_s: float) -> DemoWebSocket:
        del timeout_s
        from urllib.parse import urlparse

        connection = DemoWebSocket(self, urlparse(url).path)
        self._connections.add(connection)
        return connection

    def unregister(self, connection: DemoWebSocket) -> None:
        self._connections.discard(connection)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._publish(), name="demo01-observation-feed")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        for connection in list(self._connections):
            connection.close()

    async def _publish(self) -> None:
        while True:
            self.robot.sync()
            self._sequence += 1
            now = time.time()
            image_payload = {
                "type": "image",
                "id": CAMERA_SOURCE,
                "seq": self._sequence,
                "timestamp": now,
                "content_type": "image/png",
                "data": base64.b64encode(_encode_png(120, 60, self.robot)).decode("ascii"),
            }
            state_payload = json.dumps(self.robot.state(), ensure_ascii=False)
            image_message = json.dumps(image_payload, ensure_ascii=False)
            for connection in list(self._connections):
                if connection.path.endswith("/ws/images"):
                    connection.push(image_message)
                elif connection.path.endswith("/ws/state"):
                    connection.push(state_payload)
            await asyncio.sleep(0.08)


class DemoCollector(ForgeObservationCollector):
    """Collector wrapper kept for demo02 imports; demo01 patches it per run."""

    def __init__(self, feed: DemoObservationFeed, *args: Any, **kwargs: Any) -> None:
        kwargs["connection_factory"] = feed.connection_factory
        super().__init__(*args, **kwargs)


class DemoGateway:
    """HTTP transport implementing the Forge Tool API contract."""

    def __init__(self, robot: DemoRobot) -> None:
        self.robot = robot

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        if method == "GET" and path == "/tools":
            return _ok({"tools": TOOL_SPECS, "api_version": "forge-tool-api.v1"})
        match = re.fullmatch(r"/tools/([^/]+)/context", path)
        if method == "GET" and match:
            spec = self._spec(match.group(1))
            if spec is None:
                return _err(404, "TOOL_NOT_FOUND", f"unknown tool: {match.group(1)}")
            return _ok(
                {
                    "tool_id": spec["tool_id"],
                    "readiness": {
                        "ready": True,
                        "checks": [{"name": "endpoint_online", "ok": True}],
                    },
                    "binding": {
                        "endpoint_id": spec["endpoint_id"],
                        "operation": spec["operation"],
                        "semantics": spec["semantics"],
                    },
                    "limits": {"opening_m": {"min": 0.0, "max": 0.105}},
                    "robot_frame_profile": spec["robot_frame_profile"],
                }
            )
        match = re.fullmatch(r"/tools/([^/]+)", path)
        if method == "GET" and match:
            spec = self._spec(match.group(1))
            return _ok(spec) if spec else _err(404, "TOOL_NOT_FOUND", f"unknown tool: {match.group(1)}")
        match = re.fullmatch(r"/tools/([^/]+)/([^/]+):invoke", path)
        if method == "POST" and match:
            endpoint_id, operation = match.group(1), match.group(2)
            if endpoint_id != "motion.relative_pose" or operation != "resolve":
                return _err(404, "ENDPOINT_NOT_FOUND", f"unknown endpoint {endpoint_id}/{operation}")
            return self._resolve_relative_pose(self._arguments(request))
        match = re.fullmatch(r"/tools/([^/]+):invoke", path)
        if method == "POST" and match:
            spec = self._spec(match.group(1))
            if spec is None:
                return _err(404, "TOOL_NOT_FOUND", f"unknown tool: {match.group(1)}")
            record = self.robot.start_action(spec["tool_id"], self._arguments(request))
            return _ok(
                {
                    "invocation_id": record["invocation_id"],
                    "attempt_id": record["attempt_id"],
                    "tool_id": spec["tool_id"],
                    "phase": "accepted",
                },
                status=202,
            )
        match = re.fullmatch(r"/invocations/([^/]+)/result", path)
        if method == "GET" and match:
            record = self.robot.invocations.get(match.group(1))
            if record is None:
                return _err(404, "INVOCATION_NOT_FOUND", "unknown invocation")
            phase = self.robot.phase_of(record)
            if phase != "completed":
                return _ok({"invocation_id": record["invocation_id"], "phase": phase}, status=202)
            return _ok(
                {
                    "invocation_id": record["invocation_id"],
                    "attempt_id": record["attempt_id"],
                    "status": "available",
                    "result": self.robot.result_of(record),
                }
            )
        match = re.fullmatch(r"/invocations/([^/]+)", path)
        if method == "GET" and match:
            record = self.robot.invocations.get(match.group(1))
            if record is None:
                return _err(404, "INVOCATION_NOT_FOUND", "unknown invocation")
            return _ok(
                {
                    "invocation_id": record["invocation_id"],
                    "attempt_id": record["attempt_id"],
                    "tool_id": record["tool_id"],
                    "phase": self.robot.phase_of(record),
                }
            )
        return _err(404, "ROUTE_NOT_FOUND", f"{method} {path}")

    @staticmethod
    def _spec(tool_id: str) -> dict[str, Any] | None:
        return next((spec for spec in TOOL_SPECS if spec["tool_id"] == tool_id), None)

    @staticmethod
    def _arguments(request: httpx.Request) -> dict[str, Any]:
        try:
            payload = json.loads(request.content.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
        arguments = payload.get("arguments")
        return arguments if isinstance(arguments, dict) else {}

    def _resolve_relative_pose(self, arguments: dict[str, Any]) -> httpx.Response:
        translation = arguments.get("translation_m") or {}
        source = dict(self.robot.tcp_pose)
        target = dict(source)
        for axis in ("x", "y", "z"):
            target[axis] = round(source[axis] + float(translation.get(axis, 0.0)), 6)
        return _ok(
            {
                "source_pose": source,
                "target_pose": target,
                "frames": {
                    "reference_frame": "arm_base",
                    "target_frame": "tcp",
                    "translation_frame": arguments.get("translation_frame", "tcp"),
                    "rotation_frame": "tcp",
                },
                "state_age_ms": 8.0,
            }
        )


def _ok(data: dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"ok": True, "data": data})


def _err(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(
        status,
        json={"ok": False, "error": {"code": code, "message": message}},
    )


class DemoVerifier:
    """Deterministic verifier with the same surface used by AgentTaskCoordinator."""

    async def verify_agent_task(
        self,
        task: AgentTaskRecord,
        *,
        events: list[dict[str, Any]],
        lessons: str,
        source: str = "auto",
        mode: str = "apply",
    ) -> tuple[VerificationVerdict, Any, VerificationAttempt]:
        del events, lessons
        records = task.execution_records
        resolve = next((item for item in records if item.tool_id == "motion.resolve_relative_pose"), None)
        move = next((item for item in records if item.tool_id == "motion.move_pose"), None)
        gripper = next((item for item in records if item.tool_id == "gripper.set_opening"), None)
        evidence_refs = [
            f"invocation:{item.invocation_id}"
            for item in (move, gripper)
            if item and item.invocation_id
        ]
        if task.evidence_bundle_ref:
            evidence_refs.append(task.evidence_bundle_ref)

        source_z = (
            float(((resolve.response or {}).get("data") or {}).get("source_pose", {}).get("z", 0.0))
            if resolve
            else 0.0
        )
        motion = (
            (((move.response or {}).get("data") or {}).get("result") or {}).get("motion_result", {})
            if move
            else {}
        )
        gripper_result = (
            (((gripper.response or {}).get("data") or {}).get("result") or {}).get("gripper_result", {})
            if gripper
            else {}
        )
        final_z = float(motion.get("final_pose", {}).get("z", 0.0))
        delta_z = final_z - source_z
        gripper_position = float(gripper_result.get("position", 0.0))

        criteria = [
            CriterionVerdict(
                criterion=task.verification.success_criteria[0],
                status=(
                    "satisfied"
                    if motion.get("error_code") == "SUCCESS" and abs(delta_z - 0.03) <= 0.002
                    else "unsatisfied"
                ),
                evidence_refs=list(evidence_refs),
            ),
            CriterionVerdict(
                criterion=task.verification.success_criteria[1],
                status=(
                    "satisfied"
                    if gripper_result.get("reached_goal") is True
                    and abs(gripper_position - 0.05) <= 0.003
                    else "unsatisfied"
                ),
                evidence_refs=list(evidence_refs),
            ),
        ]
        success = all(item.status == "satisfied" for item in criteria)
        verdict = VerificationVerdict(
            verdict="success" if success else "failure",
            criteria=criteria,
            evidence_refs=evidence_refs,
            reason=(
                "TCP height and gripper opening match the requested targets."
                if success
                else "One or more Demo 01 targets were not reached."
            ),
            lesson="Execution facts and before/after evidence were checked before closing the AgentTask.",
        )
        attempt = VerificationAttempt(
            attempt_id=f"verification_{uuid4().hex[:12]}",
            source=source,  # type: ignore[arg-type]
            mode=mode,  # type: ignore[arg-type]
            verdict=verdict.verdict,
        )
        return verdict, {"task_id": task.task_id}, attempt

    def stop(self) -> None:
        return None


class Demo01Runner:
    """Run Demo 01 and emit small state updates for the TUI."""

    progress_delays_s = (1.1, 1.5, 1.9, 2.3, 1.7, 2.6, 2.0, 3.0)
    final_delay_s = 2.4

    STAGES = (
        "AgentTask created",
        "Runtime discovered",
        "Plan resolved",
        "Action accepted",
        "Robot observed",
        "Evidence captured",
        "Verifier closed",
    )

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self._coordinator: AgentTaskCoordinator | None = None
        self._client: ForgeToolClient | None = None
        self._record: AgentTaskRecord | None = None
        self._feed: DemoObservationFeed | None = None
        self._robot: DemoRobot | None = None

    async def run(self, sink: EventSink) -> AgentTaskRecord:
        await self._emit(
            sink,
            {
                "kind": "reset",
                "title": "Demo 01 · Trusted execution pipeline",
                "description": "收到 AgentTask：TCP 沿 +Z 抬高 3 cm，并把夹爪打开到 5 cm。接下来每一步都会先落账再显示。",
                "stages": list(self.STAGES),
                "dashboard": self._dashboard(),
            },
        )
        self._prepare_workspace()
        robot = DemoRobot()
        gateway = DemoGateway(robot)
        feed = DemoObservationFeed(robot)
        client = ForgeToolClient(DEMO_BASE_URL, timeout_s=2.0, transport=gateway.transport())
        config = ForgeConfig(
            request_timeout_s=2.0,
            poll_interval_s=0.12,
            execution_timeout_s=8.0,
            evidence=ForgeEvidenceConfig(
                required_image_sources=[CAMERA_SOURCE],
                capture_timeout_s=2.0,
                post_capture_timeout_s=2.0,
                connection_timeout_s=0.5,
            ),
        )
        coordinator = AgentTaskCoordinator(
            workspace=self.workspace,
            config=config,
            client=client,
            verifier=DemoVerifier(),
        )
        self._coordinator = coordinator
        self._client = client
        self._feed = feed
        self._robot = robot

        original_collector = forge_task_module.ForgeObservationCollector

        class BoundDemoCollector(ForgeObservationCollector):
            def __init__(self, base_url: str, **kwargs: Any) -> None:
                kwargs["connection_factory"] = feed.connection_factory
                super().__init__(base_url, **kwargs)

        forge_task_module.ForgeObservationCollector = BoundDemoCollector
        try:
            await feed.start()
            await self._emit(
                sink,
                {
                    "kind": "audit",
                    "message": "runtime_bootstrap: gateway + observation feed + robot state stream online",
                    "dashboard": self._dashboard(
                        task="drafting",
                        forge="gateway online",
                        robot=robot,
                        evidence="pending",
                        verifier="waiting",
                    ),
                },
            )
            tools = await client.list_tools()
            await self._emit(
                sink,
                {
                    "kind": "audit",
                    "message": "capability_discovered: action=motion.move_pose + gripper.set_opening source=top_camera",
                    "capabilities": coordinator.capabilities_summary(),
                    "tools": tools.get("data", {}),
                    "dashboard": self._dashboard(
                        task="drafting",
                        forge="runtime ready",
                        robot=robot,
                        evidence="source ready",
                        verifier="waiting",
                    ),
                },
            )
            contract = TaskVerificationContract(
                mode="enforce",
                goal="TCP 抬高 3 cm 且夹爪张开到 5 cm",
                success_criteria=[
                    "机械臂 TCP 最终位姿相对动作前位姿沿 +Z 方向升高 0.03 m (容差 ±2 mm)",
                    "夹爪总开度到达 0.05 m 且 gripper_result.reached_goal 为 true",
                ],
                constraints=["臂部动作与夹爪动作不得并发"],
                evidence_policy=VerificationEvidencePolicy(
                    required_kinds=["rgb_image", "robot_state"],
                    required_sources=[CAMERA_SOURCE],
                ),
            )
            task = coordinator.create_task(
                task_description="把机械臂末端沿 +Z 抬高 3 cm，然后把夹爪张开到 5 cm。",
                verification=contract,
                origin_session_key="demo01",
            )
            if inspect.isawaitable(task):
                task = await task
            self._record = task
            task_id = task.task_id
            await self._emit(
                sink,
                {
                    "kind": "stage",
                    "stage": 0,
                    "status": "success",
                    "message": f"AgentTask created: success criteria + evidence policy attached | {task_id}",
                    "session_id": task_id,
                    "dashboard": self._dashboard(
                        task="created",
                        forge="task accepted",
                        robot=robot,
                        evidence="before pending",
                        verifier="waiting",
                    ),
                },
            )
            await self._emit(
                sink,
                {
                    "kind": "stage",
                    "stage": 1,
                    "status": "success",
                    "message": "Runtime discovered: motion/gripper action and top_camera evidence stream are ready",
                    "capabilities": coordinator.capabilities_summary(),
                    "dashboard": self._dashboard(
                        task="created",
                        forge="tools ready",
                        robot=robot,
                        evidence="source ready",
                        verifier="waiting",
                    ),
                },
            )
            query_args = {
                "group_name": "piper_arm",
                "target_frame": "tcp",
                "reference": "current",
                "translation_frame": "tcp",
                "translation_m": {"x": 0.0, "y": 0.0, "z": 0.03},
                "orientation_mode": "preserve",
                "axis_angle_rad": None,
                "max_state_age_ms": 200,
            }
            resolve_resp = await coordinator.invoke_query(task_id, "motion.resolve_relative_pose", query_args)
            target_pose = resolve_resp["data"]["target_pose"]
            await self._emit(
                sink,
                {
                    "kind": "stage",
                    "stage": 2,
                    "status": "success",
                    "message": f"Plan resolved: +Z 0.030 m -> target tcp.z={target_pose['z']:.3f} m, gripper=0.050 m",
                    "robot": robot.state(),
                    "dashboard": self._dashboard(
                        task="planned",
                        forge="query recorded",
                        robot=robot,
                        evidence="before pending",
                        verifier="waiting",
                    ),
                },
            )
            move_args = {
                "group_name": "piper_arm",
                "reference_frame": "arm_base",
                "target_frame": "tcp",
                "target_pose": target_pose,
                "velocity_scale": 0.3,
                "acceleration_scale": 0.3,
                "position_tolerance_m": 0.002,
                "orientation_tolerance_rad": 0.01,
            }
            accepted = await coordinator.start_action(task_id, "motion.move_pose", move_args)
            move_invocation = accepted["data"]["invocation_id"]
            await self._emit(
                sink,
                {
                    "kind": "stage",
                    "stage": 3,
                    "status": "running",
                    "message": "Forge accepted motion.move_pose; accepted means scheduled, not completed",
                    "robot": robot.state(),
                    "dashboard": self._dashboard(
                        task="executing",
                        forge="motion accepted",
                        robot=robot,
                        evidence="before captured",
                        verifier="waiting",
                    ),
                },
            )
            await self._track_motion(robot, sink, coordinator, client, task_id, move_invocation)
            accepted = await coordinator.start_action(task_id, "gripper.set_opening", {"opening_m": 0.05})
            gripper_invocation = accepted["data"]["invocation_id"]
            await self._emit(
                sink,
                {
                    "kind": "stage",
                    "stage": 3,
                    "status": "running",
                    "message": "Forge accepted gripper.set_opening; gripper target=0.050 m",
                    "robot": robot.state(),
                    "dashboard": self._dashboard(
                        task="executing",
                        forge="gripper accepted",
                        robot=robot,
                        evidence="before captured",
                        verifier="waiting",
                    ),
                },
            )
            await self._track_motion(robot, sink, coordinator, client, task_id, gripper_invocation)
            final = await coordinator.finalize_task(task_id)
            self._record = final
            await self._emit(
                sink,
                {
                    "kind": "stage",
                    "stage": 4,
                    "status": "success" if final.status.value == "succeeded" else "error",
                    "message": f"Robot observed at target: tcp.z={robot.state()['tcp_pose']['z']:.3f} m, gripper={robot.state()['gripper_opening_m']:.3f} m",
                    "robot": robot.state(),
                    "dashboard": self._dashboard(
                        task="observed",
                        forge="actions completed",
                        robot=robot,
                        evidence="after captured",
                        verifier="checked",
                    ),
                },
            )
            await self._emit(
                sink,
                {
                    "kind": "stage",
                    "stage": 5,
                    "status": "success" if final.evidence_bundle_ref else "error",
                    "message": f"Evidence captured: before + after snapshots retained | {final.evidence_bundle_ref or 'none'}",
                    "artifacts": self._artifact_summary(final),
                    "dashboard": self._dashboard(
                        task="observed",
                        forge="actions completed",
                        robot=robot,
                        evidence="bundle ready",
                        verifier="checked",
                    ),
                },
            )
            await self._emit(
                sink,
                {
                    "kind": "stage",
                    "stage": 6,
                    "status": "success" if final.status.value == "succeeded" else "error",
                    "message": final.verdict.reason if final.verdict else "未生成验收结论",
                    "verification": final.verdict.model_dump(mode="json") if final.verdict else {},
                    "dashboard": self._dashboard(
                        task=final.status.value,
                        forge="task closed",
                        robot=robot,
                        evidence="bundle ready",
                        verifier=final.verdict.verdict if final.verdict else "unknown",
                    ),
                },
            )
            await self._emit(
                sink,
                {
                    "kind": "audit",
                    "level": "INFO",
                    "message": "task_verified: AgentTask closed, SQLite record and evidence artifacts retained",
                    "artifacts": self._artifact_summary(final),
                    "dashboard": self._dashboard(
                        task=final.status.value,
                        forge="task closed",
                        robot=robot,
                        evidence="bundle ready",
                        verifier=final.verdict.verdict if final.verdict else "unknown",
                    ),
                },
            )
            await self._emit(
                sink,
                {
                    "kind": "done",
                    "status": final.status.value,
                    "record": final.model_dump(mode="json"),
                    "robot": robot.state(),
                    "verification": final.verdict.model_dump(mode="json") if final.verdict else {},
                    "artifacts": self._artifact_summary(final),
                    "dashboard": self._dashboard(
                        task=final.status.value,
                        forge="task closed",
                        robot=robot,
                        evidence="bundle ready",
                        verifier=final.verdict.verdict if final.verdict else "unknown",
                    ),
                },
            )
            return final
        finally:
            forge_task_module.ForgeObservationCollector = original_collector
            await feed.stop()
            await client.close()
            self._coordinator = None
            self._client = None

    async def _track_motion(
        self,
        robot: DemoRobot,
        sink: EventSink,
        coordinator: AgentTaskCoordinator,
        client: ForgeToolClient,
        task_id: str,
        invocation_id: str,
    ) -> dict[str, Any]:
        observed: set[str] = set()
        while True:
            status = await client.invocation_status(invocation_id)
            coordinator.observe_action(task_id, invocation_id, status)
            state = robot.state()
            tcp_z = float(state["tcp_pose"]["z"])
            gripper = float(state["gripper_opening_m"])
            marker = f"{round(tcp_z, 3)}:{round(gripper, 3)}"
            if marker not in observed and (tcp_z > 0.211 or gripper > 0.0):
                observed.add(marker)
                await self._emit(
                    sink,
                    {
                        "kind": "stage",
                        "stage": 4,
                        "status": "running",
                        "message": f"Observation stream updated: tcp.z={tcp_z:.3f} m, gripper={gripper:.3f} m",
                        "robot": state,
                        "dashboard": self._dashboard(
                            task="executing",
                            forge="observing",
                            robot=robot,
                            evidence="before captured",
                            verifier="waiting",
                        ),
                    },
                )
            if status["data"].get("phase") in {"completed", "failed", "cancelled", "stopped"}:
                break
            await asyncio.sleep(0.12)
        result = await client.invocation_result(invocation_id)
        coordinator.observe_action(task_id, invocation_id, result)
        return result

    async def stop(self) -> None:
        if self._coordinator is not None and self._record is not None:
            await self._coordinator.cancel_task(
                self._record.task_id,
                reason="demo01_stopped_from_tui",
            )

    def _prepare_workspace(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        (self.workspace / ".paos" / "agent_tasks").mkdir(parents=True, exist_ok=True)
        (self.workspace / "artifacts" / "agent_tasks").mkdir(parents=True, exist_ok=True)

    def _dashboard(
        self,
        *,
        task: str = "received",
        forge: str = "initializing",
        robot: DemoRobot | None = None,
        evidence: str = "pending",
        verifier: str = "waiting",
    ) -> dict[str, str]:
        if robot is None:
            tcp = "0.210 -> 0.240 m"
            gripper = "0.000 -> 0.050 m"
        else:
            state = robot.state()
            tcp = f"{float(state['tcp_pose']['z']):.3f} -> 0.240 m"
            gripper = f"{float(state['gripper_opening_m']):.3f} -> 0.050 m"
        return {
            "AgentTask": task,
            "Forge": forge,
            "TCP z": tcp,
            "Gripper": gripper,
            "Evidence": evidence,
            "Verifier": verifier,
        }

    def _artifact_summary(self, record: AgentTaskRecord) -> list[str]:
        if not record.evidence_bundle_ref:
            return []
        root = self.workspace / Path(record.evidence_bundle_ref).parent
        return [
            str(root / "evidence_bundle.json"),
            str(root / "before_snapshot.json"),
            str(root / "after_snapshot.json"),
        ]

    @staticmethod
    async def _emit(sink: EventSink, event: dict[str, Any]) -> None:
        result = sink(event)
        if inspect.isawaitable(result):
            await result

