"""
Franka pick / place for Merom multi-robot rollout.

Control stack mirrors ``internutopia/demo/franka_manipulation_mocap_teleop.py``:
``rmpflow_controller`` + ``gripper_controller`` (RMPFlow sub-controller inside
``FrankaMocapTeleopController``, without mocap input). Phase timing follows
``test3_multi_robot_debug.py`` / ``FrankaManipulationAPI``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Sequence

import numpy as np

# Same controller names as InternUtopia Franka configs
ARM_IK_CONTROLLER = "arm_ik_controller"
RMPFLOW_CONTROLLER = "rmpflow_controller"
GRIPPER_CONTROLLER = "gripper_controller"
FRANKA_IK_JOINT_LOCK: list[Any] = [None, None]
DEFAULT_EEF_ORIENTATION = (0.0, 0.0, 1.0, 0.0)
DEFAULT_FRANKA_HOME_JOINTS: tuple[float, ...] = (
    0.0,
    -0.785,
    0.0,
    -2.356,
    0.0,
    1.571,
    0.785,
    0.04,
    0.04,
)
EEF_GOAL_THRESHOLD = 0.025
EEF_GOAL_STABLE_STEPS = 15
MIN_MOTION_STEPS = 45
MIN_IK_MOTION_STEPS = 30


@dataclass
class FrankaPickPlaceConfig:
    pause_steps: int = 60
    gripper_settle_steps: int = 60
    max_steps_per_phase: int = 1500
    arm_waypoint_count: int = 24
    release_pause_steps: int = 150
    release_waypoint_count: int = 24
    motion_steps_per_waypoint: int = 180
    ik_min_motion_steps: int = 30
    arm_controller: str = ARM_IK_CONTROLLER
    robot_base_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    use_robot_base_frame: bool = False


@dataclass
class ManipulationTarget:
    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float] = DEFAULT_EEF_ORIENTATION
    pre_position: tuple[float, float, float] | None = None
    post_position: tuple[float, float, float] | None = None
    name: str = ""


@dataclass
class PickPlaceResult:
    action: str
    success: bool
    steps: int
    trace: list[dict[str, Any]] = field(default_factory=list)
    failed_phase: str = ""


StepFn = Callable[[dict[str, Any]], tuple[dict[str, Any], bool]]
ObsFn = Callable[[], dict[str, Any]]


def _as_xyz(value: Sequence[float] | None, default_z: float = 0.0) -> tuple[float, float, float]:
    if value is None:
        return (0.0, 0.0, default_z)
    return (float(value[0]), float(value[1]), float(value[2]))


def _as_quat(value: Sequence[float] | None) -> tuple[float, float, float, float]:
    if value is None:
        return DEFAULT_EEF_ORIENTATION
    return (
        float(value[0]),
        float(value[1]),
        float(value[2]),
        float(value[3]),
    )


def coerce_manipulation_target(
    raw: dict[str, Any] | ManipulationTarget,
    *,
    default_name: str = "",
) -> ManipulationTarget:
    if isinstance(raw, ManipulationTarget):
        return raw
    pos = _as_xyz(raw.get("position"))
    pre = raw.get("pre_position")
    post = raw.get("post_position")
    return ManipulationTarget(
        name=str(raw.get("name") or default_name),
        position=pos,
        orientation=_as_quat(raw.get("orientation")),
        pre_position=None if pre is None else _as_xyz(pre),
        post_position=None if post is None else _as_xyz(post),
    )


def resolve_blue_cube_grasp_target(objects: list[dict[str, Any]]) -> dict[str, Any] | None:
    cube_candidates: list[dict[str, Any]] = []
    for item in objects:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip().lower()
        if "cube" not in name:
            continue
        pos = item.get("position")
        if not (isinstance(pos, (list, tuple)) and len(pos) >= 3):
            continue
        color = item.get("color")
        blue_score = -1.0
        if isinstance(color, (list, tuple)) and len(color) >= 3:
            try:
                blue_score = float(color[2]) - 0.5 * float(color[0]) - 0.5 * float(color[1])
            except (TypeError, ValueError):
                blue_score = -1.0
        cube_candidates.append({
            "name": item.get("name", "cube"),
            "position": [float(pos[0]), float(pos[1]), float(pos[2])],
            "blue_score": blue_score,
        })
    if not cube_candidates:
        return None
    chosen = sorted(cube_candidates, key=lambda x: x["blue_score"], reverse=True)[0]
    x, y, z = chosen["position"]
    return {
        "name": str(chosen.get("name") or "blue_cube"),
        "position": [x, y, z],
        "pre_position": [x, y, z + 0.18],
        "post_position": [x, y, z + 0.12],
        "orientation": list(DEFAULT_EEF_ORIENTATION),
        "metadata": {"auto_resolved": True, "source": "objects_spec"},
    }


def world_to_robot_base(
    world_xyz: Sequence[float],
    base_xyz: Sequence[float],
) -> tuple[float, float, float]:
    wx, wy, wz = _as_xyz(world_xyz)
    bx, by, bz = _as_xyz(base_xyz)
    return (wx - bx, wy - by, wz - bz)


def franka_ik_joint_lock_action() -> dict[str, list[Any]]:
    """Lock arm joints at current q (InternUtopia IK ``forward(None, ...)``)."""
    return {ARM_IK_CONTROLLER: list(FRANKA_IK_JOINT_LOCK)}


def augment_franka_action(
    obs: dict[str, Any],
    action: dict[str, Any],
    *,
    robot_base: Sequence[float] | None = None,
    arm_controller: str = RMPFLOW_CONTROLLER,
) -> dict[str, Any]:
    """Hold arm on gripper-only / empty steps without chasing noisy eef obs."""
    act = dict(action or {})
    names = set(act.keys())
    if arm_controller in names:
        act.pop("arm_joint_controller", None)
        if arm_controller == ARM_IK_CONTROLLER:
            act.pop(RMPFLOW_CONTROLLER, None)
        else:
            act.pop(ARM_IK_CONTROLLER, None)
        return act
    if "arm_joint_controller" in names:
        act.pop(ARM_IK_CONTROLLER, None)
        act.pop(RMPFLOW_CONTROLLER, None)
        return act
    if names and names - {GRIPPER_CONTROLLER}:
        return act
    if arm_controller == ARM_IK_CONTROLLER:
        act.update(franka_ik_joint_lock_action())
        return act
    eef_pos = obs.get("eef_position")
    eef_ori = obs.get("eef_orientation")
    if eef_pos is None or eef_ori is None:
        return act
    hold_pos = list(eef_pos)
    if robot_base is not None:
        hold_pos = list(world_to_robot_base(eef_pos, robot_base))
    act.setdefault(
        arm_controller,
        [np.array(hold_pos, dtype=float), np.array(eef_ori, dtype=float)],
    )
    return act


def apply_mocap_franka_gains(articulation: Any) -> bool:
    """Match ``MocapControlledFrankaRobot.post_reset`` PD tuning."""
    try:
        view = articulation._articulation_view
        view.set_max_joint_velocities([1.0] * 9)
        stiffnesses = np.array([1e7, 1e7, 1e7, 1e7, 1e7, 1e7, 1e7, 1e4, 0.0])
        dampings = np.array([1e6, 1e6, 1e6, 1e6, 1e6, 1e6, 1e6, 1e3, 0.0])
        view.set_gains(kps=stiffnesses, kds=dampings)
        return True
    except Exception:
        try:
            stiffnesses = np.array([1e7, 1e7, 1e7, 1e7, 1e7, 1e7, 1e7, 1e4, 0.0])
            dampings = np.array([1e6, 1e6, 1e6, 1e6, 1e6, 1e6, 1e6, 1e3, 0.0])
            articulation.set_gains(kps=stiffnesses, kds=dampings)
            return True
        except Exception:
            return False


class FrankaPickPlaceExecutor:
    """Pick / place via arm IK or RMPFlow + gripper (InternUtopia test3 stack)."""

    def __init__(
        self,
        step_fn: StepFn,
        get_obs_fn: ObsFn,
        config: FrankaPickPlaceConfig | None = None,
    ) -> None:
        self._step = step_fn
        self._get_obs = get_obs_fn
        self.cfg = config or FrankaPickPlaceConfig()
        self._pause_steps = self.cfg.pause_steps
        self._arm_waypoint_count = self.cfg.arm_waypoint_count

    @property
    def _uses_ik(self) -> bool:
        return self.cfg.arm_controller == ARM_IK_CONTROLLER

    @property
    def pause_steps(self) -> int:
        return self._pause_steps

    @pause_steps.setter
    def pause_steps(self, value: int) -> None:
        self._pause_steps = max(1, int(value))

    @property
    def arm_waypoint_count(self) -> int:
        return self._arm_waypoint_count

    @arm_waypoint_count.setter
    def arm_waypoint_count(self, value: int) -> None:
        self._arm_waypoint_count = max(1, int(value))

    def pick(self, target: ManipulationTarget | dict[str, Any]) -> PickPlaceResult:
        tgt = coerce_manipulation_target(target, default_name="pick")
        return self._run_pick_or_place("pick", tgt, gripper_command="close")

    def release(self, target: ManipulationTarget | dict[str, Any]) -> PickPlaceResult:
        tgt = coerce_manipulation_target(target, default_name="place")
        return self._run_pick_or_place("release", tgt, gripper_command="open")

    def pick_and_place(
        self,
        grasp: ManipulationTarget | dict[str, Any],
        place: ManipulationTarget | dict[str, Any],
    ) -> PickPlaceResult:
        pick_result = self.pick(grasp)
        if not pick_result.success:
            return pick_result
        orig_pause = self.pause_steps
        orig_wp = self.arm_waypoint_count
        try:
            self.pause_steps = self.cfg.release_pause_steps
            self.arm_waypoint_count = self.cfg.release_waypoint_count
            release_result = self.release(place)
        finally:
            self.pause_steps = orig_pause
            self.arm_waypoint_count = orig_wp
        if not release_result.success:
            return release_result
        return PickPlaceResult(
            action="pick_place",
            success=True,
            steps=pick_result.steps + release_result.steps,
            trace=[*pick_result.trace, *release_result.trace],
        )

    def _control_xyz(self, world_xyz: Sequence[float]) -> tuple[float, float, float]:
        if not self.cfg.use_robot_base_frame:
            return _as_xyz(world_xyz)
        return world_to_robot_base(world_xyz, self.cfg.robot_base_position)

    def _arm_action(
        self,
        world_position: Sequence[float],
        orientation: Sequence[float],
    ) -> dict[str, list[np.ndarray]]:
        ctrl = self._control_xyz(world_position)
        return {
            self.cfg.arm_controller: [
                np.array(ctrl, dtype=float),
                np.array(_as_quat(orientation), dtype=float),
            ]
        }

    def _gripper_action(self, command: Literal["open", "close"]) -> dict[str, list[str]]:
        return {GRIPPER_CONTROLLER: [command]}

    def _merge_hold_and_gripper(
        self,
        hold_position: Sequence[float],
        hold_orientation: Sequence[float],
        gripper_command: Literal["open", "close"],
    ) -> dict[str, Any]:
        action = self._arm_action(hold_position, hold_orientation)
        action.update(self._gripper_action(gripper_command))
        return action

    def _env_step(self, action: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        obs = self._get_obs()
        action = augment_franka_action(
            obs,
            action,
            robot_base=self.cfg.robot_base_position if self.cfg.use_robot_base_frame else None,
            arm_controller=self.cfg.arm_controller,
        )
        return self._step(action)

    def _controller_finished(self, obs: dict[str, Any]) -> bool:
        ctrl = (obs.get("controllers") or {}).get(self.cfg.arm_controller) or {}
        if not bool(ctrl.get("finished")):
            return False
        if self._uses_ik and ctrl.get("success") is False:
            return False
        return True

    def _ik_hold_action(self) -> dict[str, Any]:
        if self._uses_ik:
            return franka_ik_joint_lock_action()
        obs = self._get_obs()
        pos = obs.get("eef_position")
        ori = obs.get("eef_orientation")
        if pos is None or ori is None:
            return {}
        return self._arm_action(pos, ori)

    def _eef_control_position(self, obs: dict[str, Any]) -> np.ndarray | None:
        eef = obs.get("eef_position")
        if eef is None:
            return None
        return np.array(self._control_xyz(eef), dtype=float)

    def _eef_distance(self, obs: dict[str, Any], world_target: Sequence[float]) -> float:
        eef_ctrl = self._eef_control_position(obs)
        if eef_ctrl is None:
            return float("inf")
        target_ctrl = np.array(self._control_xyz(world_target), dtype=float)
        return float(np.linalg.norm(eef_ctrl - target_ctrl))

    def _run_until_at_target(
        self,
        action: dict[str, Any],
        target_position: Sequence[float],
        phase: str,
    ) -> tuple[bool, list[dict[str, Any]], dict[str, Any]]:
        trace: list[dict[str, Any]] = []
        final_obs: dict[str, Any] = {}
        stable = 0
        max_steps = max(
            self.cfg.max_steps_per_phase,
            self.cfg.motion_steps_per_waypoint,
        )
        for step_i in range(1, max_steps + 1):
            final_obs, terminated = self._env_step(action)
            trace.append({"step": step_i, "phase": phase})
            dist = self._eef_distance(final_obs, target_position)
            if dist <= EEF_GOAL_THRESHOLD:
                stable += 1
            else:
                stable = 0
            if step_i >= MIN_MOTION_STEPS and stable >= EEF_GOAL_STABLE_STEPS:
                return True, trace, final_obs
            if terminated:
                return False, trace, final_obs
        return False, trace, final_obs

    def _run_until_controller_finished(
        self,
        action: dict[str, Any],
        phase: str,
    ) -> tuple[bool, list[dict[str, Any]], dict[str, Any]]:
        trace: list[dict[str, Any]] = []
        final_obs: dict[str, Any] = {}
        max_steps = max(
            self.cfg.max_steps_per_phase,
            self.cfg.motion_steps_per_waypoint,
        )
        min_steps = MIN_IK_MOTION_STEPS if self._uses_ik else MIN_MOTION_STEPS
        for step_i in range(1, max_steps + 1):
            final_obs, terminated = self._env_step(action)
            trace.append({"step": step_i, "phase": phase})
            if step_i >= min_steps and self._controller_finished(final_obs):
                return True, trace, final_obs
            if terminated:
                return False, trace, final_obs
        return False, trace, final_obs

    def _run_motion_segment(
        self,
        action: dict[str, Any],
        target_position: Sequence[float],
        phase: str,
    ) -> tuple[bool, list[dict[str, Any]], dict[str, Any]]:
        if self._uses_ik:
            return self._run_until_controller_finished(action, phase)
        return self._run_until_at_target(action, target_position, phase)

    def _run_cartesian_motion(
        self,
        destination: Sequence[float],
        orientation: Sequence[float],
        phase: str,
    ) -> tuple[bool, list[dict[str, Any]], dict[str, Any]]:
        obs = self._get_obs()
        eef_ctrl = self._eef_control_position(obs)
        dest_ctrl = np.array(self._control_xyz(destination), dtype=float)
        if eef_ctrl is None:
            waypoints_ctrl = [dest_ctrl]
        else:
            start = eef_ctrl
            count = self.arm_waypoint_count
            waypoints_ctrl = [
                start + (dest_ctrl - start) * (idx / count) for idx in range(1, count + 1)
            ]

        total_trace: list[dict[str, Any]] = []
        final_obs: dict[str, Any] = {}
        ori = _as_quat(orientation)
        for idx, waypoint_ctrl in enumerate(waypoints_ctrl, start=1):
            if self.cfg.use_robot_base_frame:
                waypoint_world = tuple(
                    waypoint_ctrl[i] + self.cfg.robot_base_position[i] for i in range(3)
                )
            else:
                waypoint_world = tuple(float(v) for v in waypoint_ctrl)
            ok, phase_trace, final_obs = self._run_motion_segment(
                self._arm_action(waypoint_world, ori),
                waypoint_world,
                f"{phase}_{idx}",
            )
            total_trace.extend(phase_trace)
            if not ok:
                return False, total_trace, final_obs
        return True, total_trace, final_obs

    def _run_fixed_steps(
        self,
        action: dict[str, Any],
        steps: int,
        phase: str,
    ) -> tuple[bool, list[dict[str, Any]], dict[str, Any]]:
        trace: list[dict[str, Any]] = []
        final_obs: dict[str, Any] = {}
        for step_i in range(1, max(1, steps) + 1):
            final_obs, terminated = self._env_step(action)
            trace.append({"step": step_i, "phase": phase})
            if terminated:
                return False, trace, final_obs
        return True, trace, final_obs

    def _run_pick_or_place(
        self,
        action_name: str,
        target: ManipulationTarget,
        *,
        gripper_command: Literal["open", "close"],
    ) -> PickPlaceResult:
        approach = target.pre_position or (
            target.position[0],
            target.position[1],
            target.position[2] + 0.1,
        )
        retreat = target.post_position or approach
        trace: list[dict[str, Any]] = []

        if gripper_command == "open":
            release_pause = max(self.pause_steps, self.cfg.gripper_settle_steps)
            phases: list[tuple[str, str, Any]] = [
                ("approach", "motion", approach),
                ("pre_gripper_pause", "pause", None),
                ("target", "motion", target.position),
                ("target_pause", "pause", None),
                ("gripper", "settle", gripper_command),
                ("release_settle", "pause_custom", release_pause),
            ]
        else:
            phases = [
                ("approach", "motion", approach),
                ("pre_gripper_pause", "pause", None),
                ("target", "motion", target.position),
                ("target_pause", "pause", None),
                ("gripper", "settle", gripper_command),
                ("post_gripper_pause", "pause", None),
                ("retreat", "motion", retreat),
            ]

        for phase_name, phase_type, phase_value in phases:
            if phase_type == "motion":
                ok, phase_trace, obs = self._run_cartesian_motion(
                    phase_value, target.orientation, phase_name
                )
            elif phase_type == "settle":
                ok, phase_trace, _ = self._run_fixed_steps(
                    self._gripper_action(phase_value),
                    self.cfg.gripper_settle_steps,
                    phase_name,
                )
            elif phase_type == "pause_custom":
                ok, phase_trace, _ = self._run_fixed_steps(
                    {},
                    int(phase_value),
                    phase_name,
                )
            else:
                ok, phase_trace, _ = self._run_fixed_steps(
                    {},
                    self.pause_steps,
                    phase_name,
                )
            trace.extend(phase_trace)
            if not ok:
                return PickPlaceResult(
                    action=action_name,
                    success=False,
                    steps=len(trace),
                    trace=trace,
                    failed_phase=phase_name,
                )

        return PickPlaceResult(
            action=action_name,
            success=True,
            steps=len(trace),
            trace=trace,
        )
