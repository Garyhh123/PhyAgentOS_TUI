"""
Merom multi-robot rollout runner (PiperGo2 + G1 in one Isaac Sim scene).

Uses InternUtopia ``vec_env.Env`` (multi-agent). Each WS step must include ``robot_id``
selecting which robot receives the action.
"""

from __future__ import annotations

import importlib
import json
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from rollout.bootstrap import REPO_ROOT, ensure_bundled_internutopia
from rollout.franka_pick_place import (
    ARM_IK_CONTROLLER,
    DEFAULT_FRANKA_HOME_JOINTS,
    FrankaPickPlaceConfig,
    FrankaPickPlaceExecutor,
    ManipulationTarget,
    RMPFLOW_CONTROLLER,
    apply_mocap_franka_gains,
    augment_franka_action,
    coerce_manipulation_target,
    franka_ik_joint_lock_action,
    resolve_blue_cube_grasp_target,
)
from rollout.pipergo2_runner import (
    PiperGo2ManipulationRunner,
    _resolve_repo_path,
    normalize_control_action,
)


@dataclass
class RobotProfile:
    robot_id: str
    robot_type: str
    position: tuple[float, float, float]
    waypoints: dict[str, list[float]]
    waypoint_aliases: dict[str, str]
    navigation_max_steps: int = 1200
    navigation_threshold: float = 0.10
    navigation_warmup_steps: int = 90
    navigation_finished_stable_steps: int = 15
    navigation_settle_steps: int = 60
    navigation_log_interval: int = 100
    navigation_action_name: str | None = None
    arm_mass_scale: float = 0.25
    freeze_base_during_arm_control: bool = True
    arm_control_action_names: list[str] = field(
        default_factory=lambda: ["arm_joint_controller", "arm_ik_controller"]
    )
    robot_usd_path: str = ""
    objects: list[dict[str, Any]] = field(default_factory=list)
    grasp_targets: dict[str, dict[str, Any]] = field(default_factory=dict)
    place_targets: dict[str, dict[str, Any]] = field(default_factory=dict)
    franka_pause_steps: int = 45
    franka_gripper_settle_steps: int = 30
    franka_max_steps_per_phase: int = 1500
    franka_arm_waypoint_count: int = 24
    franka_release_pause_steps: int = 150
    franka_release_waypoint_count: int = 24
    franka_motion_steps_per_waypoint: int = 180
    franka_ik_min_motion_steps: int = 30
    franka_cube_mass: float = 0.02
    franka_use_rmpflow: bool = False
    franka_initial_joint_positions: list[float] = field(
        default_factory=lambda: list(DEFAULT_FRANKA_HOME_JOINTS)
    )
    franka_initial_settle_steps: int = 60
    forward_speed: float | None = None
    rotation_speed: float | None = None
    rotate_speed: float | None = None
    move_to_point_threshold: float | None = None
    include_arm_joint_controller: bool = False


class _FrankaEnvView:
    """Present multi-robot vec env as single-robot env for FrankaManipulationAPI."""

    def __init__(
        self, runner: "MeromMultiRobotRunner", robot_id: str, profile: "RobotProfile"
    ) -> None:
        self._runner = runner
        self._robot_id = robot_id
        self._profile = profile

    @staticmethod
    def _as_bool_flag(value: Any) -> bool:
        """vec_env returns list[bool]; FrankaManipulationAPI expects a scalar bool."""
        if isinstance(value, (list, tuple)):
            return any(bool(x) for x in value)
        return bool(value)

    def _unwrap(self, raw_obs: Any) -> dict[str, Any]:
        block = self._runner._extract_robot_obs(
            raw_obs, robot_id=self._robot_id, robot_type=self._profile.robot_type
        )
        return dict(block or {})

    def get_observations(self) -> dict[str, Any]:
        raw = self._runner._last_obs
        if raw is None and self._runner._env is not None:
            try:
                raw = self._runner._env.get_observations()
            except Exception:
                return {}
        if raw is None:
            return {}
        return self._unwrap(raw)

    def _augment_action(self, action: dict[str, Any]) -> dict[str, Any]:
        return self._runner._augment_franka_action(
            self._robot_id, self._profile, action
        )

    def step(
        self, action: dict[str, Any] | None = None, **kwargs: Any
    ) -> tuple[Any, ...]:
        act = action if action is not None else dict(kwargs.get("action") or {})
        act = self._augment_action(act)
        with self._runner._env_lock:
            raw, reward, terminated, truncated, info = self._runner._env_step(
                self._robot_id, act
            )
        self._runner._last_obs = raw
        return (
            self._unwrap(raw),
            reward,
            self._as_bool_flag(terminated),
            self._as_bool_flag(truncated),
            info,
        )

    def reset(self) -> tuple[Any, Any]:
        return self.get_observations(), {}


class MeromMultiRobotRunner:
    """Single-env multi-robot runner for Merom scene (pipergo2 + g1)."""

    def __init__(self, config: dict[str, Any], *, gui: bool = False) -> None:
        self.config = dict(config)
        self.gui = bool(gui)
        self._env = None
        self._env_lock = threading.RLock()
        self._last_obs: Any = None
        self._started = False

        self._scene_asset_path = str(config.get("scene_asset_path", "")).strip()
        self._objects_spec = list(config.get("objects", []))
        self._api_kwargs = dict(config.get("api_kwargs", {}))
        self._api_kwargs["force_gui"] = self.gui
        self._api_kwargs.pop("headless", None)
        self._isaac_env_cfg = config.get("isaac_env")
        self._room_bootstrap = dict(config.get("room_bootstrap", {}))
        self._room_lighting = str(config.get("room_lighting", "grey_studio")).strip().lower()
        self._collision_patch = bool(config.get("enable_static_scene_mesh_collision_patch", True))

        self._robots: dict[str, RobotProfile] = self._parse_robots(config.get("robots") or {})
        if not self._robots:
            raise ValueError("merom_multi_robot config requires non-empty 'robots' map")
        self._franka_pick_place: dict[str, FrankaPickPlaceExecutor] = {}
        self._default_robot_id = str(config.get("default_robot_id", "pipergo2"))
        if self._default_robot_id not in self._robots:
            self._default_robot_id = next(iter(self._robots))

        self._idle_step_enabled = bool(config.get("idle_step_enabled", True))
        self._idle_steps_per_cycle = int(config.get("idle_steps_per_cycle", 1))
        self._idle_step_interval_s = float(config.get("idle_step_interval_s", 1.0 / 30.0))
        self._last_idle_step_ts = 0.0

        self._pipergo2_view = None
        self._frozen_pose: tuple[Any, Any] | None = None
        self._scene_narration_cn = "Merom multi-robot scene (pipergo2 + g1 + franka)."
        self._camera_eye_offset = tuple(config.get("camera_eye_offset", (2.5, 2.5, 2.0)))
        self._camera_target_z_offset = float(config.get("camera_target_z_offset", 0.0))
        self._camera_target_min_z = float(config.get("camera_target_min_z", 0.2))

        ensure_bundled_internutopia()

    def health(self) -> dict[str, Any]:
        return {
            "runner": "merom_multi_robot",
            "started": self._started,
            "robot_ids": sorted(self._robots.keys()),
            "default_robot_id": self._default_robot_id,
        }

    def reset(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        active_robot = str(payload.get("robot_id") or self._default_robot_id).strip()
        if active_robot not in self._robots:
            active_robot = self._default_robot_id

        if self._started and self._env is not None and not payload.get("force", False):
            spawn = self._verify_spawned_robots()
            self._trace(
                f"reset reused env; active_robot={active_robot!r} spawn_check={spawn}"
            )
            return {
                "obs": self.build_observation(active_robot),
                "info": {
                    "message": "already_started",
                    "reused": True,
                    "robot_id": active_robot,
                    "spawn_check": spawn,
                },
            }

        if self._env is not None:
            self.close()

        if self.gui and self._isaac_env_cfg:
            try:
                from rollout.simulation.isaac_bootstrap import bootstrap_isaac_env

                bootstrap_isaac_env(self._isaac_env_cfg, want_gui=True)
            except Exception as exc:
                print(f"[rollout/merom] WARNING: isaac bootstrap skipped: {exc}")

        scene_path = _resolve_repo_path(
            str(payload.get("scene_asset_path", self._scene_asset_path))
        )
        if not scene_path.exists():
            raise FileNotFoundError(f"scene file not found: {scene_path}")

        self._env = self._build_vec_env(str(scene_path))
        observations, _ = self._env.reset()
        self._last_obs = observations[0] if observations else {}
        self._started = True
        self._init_pipergo2_freeze_view()

        boot_info: dict[str, Any] = {}
        spawn_check = self._verify_spawned_robots()
        boot_info["spawn_check"] = spawn_check
        missing = [rid for rid, st in spawn_check.items() if st != "ok"]
        if missing:
            self._trace(f"WARNING: robots missing on stage: {missing}")

        rb = dict(self._room_bootstrap)
        rb.update(payload.get("room_bootstrap") or {})
        if rb.get("enabled", True):
            boot_info["bootstrap"] = self._room_bootstrap_sequence(rb, focus_robot_id=active_robot)
            boot_info["spawn_settle"] = self._post_spawn_settle(rb)
        if self._collision_patch:
            try:
                self._collision_patch_merom_scene()
                boot_info["collision_patch"] = "ok"
            except Exception as exc:
                boot_info["collision_patch"] = f"skipped:{exc}"

        boot_info["object_masses"] = self._apply_merom_object_masses()
        boot_info["franka_initial_pose"] = self._apply_franka_initial_joint_pose()
        boot_info["franka_rmpflow_tuning"] = self._apply_merom_franka_rmpflow_tuning()

        self._trace(f"reset started robots={sorted(self._robots.keys())} active={active_robot!r}")

        return {
            "obs": self.build_observation(active_robot),
            "info": {
                "message": "started",
                "scene_asset_path": str(scene_path),
                "robot_ids": sorted(self._robots.keys()),
                "active_robot_id": active_robot,
                **boot_info,
            },
        }

    def observe(self) -> dict[str, Any]:
        if not self._started or self._env is None:
            raise RuntimeError("rollout not started; call reset first")
        self._idle_step_if_due()
        return self.build_observation(self._default_robot_id)

    def step(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._started or self._env is None:
            raise RuntimeError("rollout not started; call reset first")

        robot_id = str(payload.get("robot_id") or self._default_robot_id).strip()
        self._trace(f"step robot_id={robot_id!r} mode={payload.get('mode', 'control')!r}")
        if robot_id not in self._robots:
            raise ValueError(
                f"unknown robot_id={robot_id!r}; known={sorted(self._robots.keys())}"
            )
        profile = self._robots[robot_id]

        mode = str(payload.get("mode", "control")).strip().lower()
        if mode == "control":
            return self._step_control(robot_id, profile, payload)
        if mode == "command":
            return self._step_command(robot_id, profile, payload)
        if mode == "language":
            text = str(payload.get("text", "")).strip()
            if not text:
                raise ValueError("language step requires payload.text")
            return self.step(
                {
                    "robot_id": robot_id,
                    "mode": "command",
                    "command": "language",
                    "params": {"text": text},
                }
            )
        raise ValueError(f"unsupported step mode: {mode}")

    def close(self) -> dict[str, Any]:
        self._clear_frozen_pose()
        self._pipergo2_view = None
        if self._env is None:
            self._started = False
            return {"info": {"message": "already_closed"}}
        try:
            self._env.close()
        finally:
            self._env = None
            self._started = False
        return {"info": {"message": "closed"}}

    def build_observation(self, robot_id: str | None = None) -> dict[str, Any]:
        rid = str(robot_id or self._default_robot_id)
        profile = self._robots.get(rid, self._robots[self._default_robot_id])
        robot = self._extract_robot_obs(self._last_obs, robot_id=rid, robot_type=profile.robot_type)
        robot_xy = PiperGo2ManipulationRunner._xy_from_robot_position(
            robot.get("position") if robot else None
        )
        if robot_xy is None:
            robot_xy = (float(profile.position[0]), float(profile.position[1]))

        return {
            "raw": self._to_builtin(self._last_obs),
            "robot": self._to_builtin(robot) if robot else None,
            "robot_id": rid,
            "robot_type": profile.robot_type,
            "robot_xy": [float(robot_xy[0]), float(robot_xy[1])],
            "runtime": {
                "location": "sim",
                "state": "running" if self._started else "idle",
                "robot_ids": sorted(self._robots.keys()),
                "active_robot_id": rid,
                "scene_description_cn": self._scene_narration_cn,
            },
            "scene_description_cn": self._scene_narration_cn,
        }

    # ── Control / command ─────────────────────────────────────────────

    def _step_control(
        self, robot_id: str, profile: RobotProfile, payload: dict[str, Any]
    ) -> dict[str, Any]:
        action = payload.get("action", {})
        if not isinstance(action, dict):
            raise ValueError("control step requires payload.action dict")
        action = normalize_control_action(action)
        sim_steps = int(payload.get("sim_steps", payload.get("repeat", 1)))
        if sim_steps < 1:
            sim_steps = 1

        freeze_base = self._should_freeze_base(profile, action)
        self._trace(
            f"robot={robot_id} control keys={list(action.keys())} "
            f"sim_steps={sim_steps} freeze_base={freeze_base}"
        )
        if freeze_base:
            self._freeze_robot_pose()

        reward = 0.0
        info: dict[str, Any] = {}
        done = False
        try:
            for sim_i in range(sim_steps):
                with self._env_lock:
                    self._last_obs, reward, terminated, truncated, info = self._env_step(
                        robot_id, action
                    )
                if freeze_base:
                    self._apply_frozen_pose()
                done = bool(terminated[0]) if isinstance(terminated, (list, tuple)) else bool(
                    terminated
                )
                if done:
                    self._trace(f"control terminated early at sim_step={sim_i + 1}/{sim_steps}")
                    break
        finally:
            if freeze_base:
                self._clear_frozen_pose()

        return {
            "obs": self.build_observation(robot_id),
            "reward": float(reward) if isinstance(reward, (int, float)) else 0.0,
            "done": done,
            "info": {
                **self._safe_dict(info),
                "robot_id": robot_id,
                "sim_steps": sim_steps,
                "sim_steps_executed": sim_i + 1,
            },
        }

    def _step_command(
        self, robot_id: str, profile: RobotProfile, payload: dict[str, Any]
    ) -> dict[str, Any]:
        command = str(payload.get("command", "")).strip()
        params = dict(payload.get("params") or {})
        self._trace(f"robot={robot_id} command={command!r} params={params}")
        message = self._dispatch_command(robot_id, profile, command, params)
        success = not (
            message.startswith("Error:")
            or message.startswith("navigate failed")
            or "FAILED" in message
        )
        return {
            "obs": self.build_observation(robot_id),
            "reward": 1.0 if success else 0.0,
            "done": False,
            "info": {
                "robot_id": robot_id,
                "command": command,
                "message": message,
                "success": success,
            },
        }

    def _dispatch_command(
        self, robot_id: str, profile: RobotProfile, command: str, params: dict[str, Any]
    ) -> str:
        if command == "language":
            return self._cmd_language(robot_id, profile, params)
        if command == "navigate_to_named":
            return self._cmd_navigate_to_named(robot_id, profile, params)
        if command == "navigate_to_waypoint":
            wp = params.get("waypoint_xy")
            if not (isinstance(wp, list) and len(wp) >= 2):
                return "Error: waypoint_xy must be [x, y]"
            return self._navigate_xy(
                robot_id,
                profile,
                [float(wp[0]), float(wp[1])],
                max_steps=int(params.get("max_steps", profile.navigation_max_steps)),
                threshold=float(params.get("threshold", profile.navigation_threshold)),
            )
        if command == "describe_visible_scene":
            return self._scene_narration_cn
        if command == "franka_grasp":
            return self._cmd_franka_manipulation(
                robot_id, profile, params, gripper_command="close"
            )
        if command == "franka_place":
            return self._cmd_franka_manipulation(
                robot_id, profile, params, gripper_command="open"
            )
        if command == "run_franka_pick_place":
            return self._cmd_franka_pick_place(robot_id, profile, params)
        return f"Error: unsupported command {command!r} for robot {robot_id}"

    def _cmd_language(self, robot_id: str, profile: RobotProfile, params: dict[str, Any]) -> str:
        text = str(params.get("text", "")).strip().lower()
        self._trace(f"robot={robot_id} language: {text!r}")
        if not text:
            return "Error: empty language text"
        if profile.robot_type == "franka":
            if any(k in text for k in ("pick", "grasp", "抓", "捡", "cube", "方块", "place", "放")):
                grasp_key = str(params.get("grasp_target") or "cube")
                place_key = str(params.get("place_target") or "pedestal")
                return self._cmd_franka_pick_place(
                    robot_id,
                    profile,
                    {"grasp_target": grasp_key, "place_target": place_key},
                )
            if any(k in text for k in ("desk", "桌", "go to", "navigate", "走到", "去")):
                return "Error: franka is fixed-base; navigation commands do not apply"
        if profile.robot_type == "pipergo2" and any(
            k in text for k in ("pick", "grasp", "抓", "捡")
        ):
            return "Error: pick/VLA not enabled in merom_multi_robot runner yet"
        if any(k in text for k in ("desk", "桌", "staging")) or (
            "table" in text
            and any(h in text for h in ("go to", "navigate", "move to", "走到", "去", "前往"))
        ):
            return self._cmd_navigate_to_named(
                robot_id, profile, {"waypoint_key": "desk", **params}
            )
        if any(
            k in text
            for k in (
                "home",
                "init",
                "start",
                "origin",
                "起点",
                "起始",
                "归位",
                "复位",
            )
        ):
            return self._cmd_navigate_to_named(
                robot_id, profile, {"waypoint_key": "home", **params}
            )
        return self._scene_narration_cn

    def _cmd_navigate_to_named(
        self, robot_id: str, profile: RobotProfile, params: dict[str, Any]
    ) -> str:
        raw_key = str(params.get("waypoint_key") or params.get("target") or "").strip()
        if not raw_key:
            return "Error: waypoint_key or target is required"
        key = self._resolve_waypoint_key(profile, raw_key)
        wp = profile.waypoints.get(key)
        if not wp:
            return f"Error: unknown waypoint_key={raw_key!r} for robot={robot_id}"
        goal = [float(wp[0]), float(wp[1])]
        self._trace(f"robot={robot_id} navigate_to_named key={key!r} goal_xy={goal}")
        return self._navigate_xy(
            robot_id,
            profile,
            goal,
            max_steps=int(params.get("max_steps", profile.navigation_max_steps)),
            threshold=float(params.get("threshold", profile.navigation_threshold)),
        )

    def _navigate_xy(
        self,
        robot_id: str,
        profile: RobotProfile,
        xy: list[float],
        *,
        max_steps: int,
        threshold: float,
    ) -> str:
        if self._env is None:
            return "Error: env not started"
        action_name = str(
            profile.navigation_action_name or self._default_nav_action_name(profile.robot_type)
        )
        robot_obs = self._extract_robot_obs(
            self._last_obs, robot_id=robot_id, robot_type=profile.robot_type
        )
        start_xy = PiperGo2ManipulationRunner._xy_from_robot_position(
            robot_obs.get("position") if robot_obs else None
        )
        if start_xy is None:
            start_xy = (float(profile.position[0]), float(profile.position[1]))

        warmup = max(0, int(profile.navigation_warmup_steps))
        if warmup > 0:
            self._trace(
                f"robot={robot_id} navigate warmup: {warmup} hold at "
                f"({start_xy[0]:.3f},{start_xy[1]:.3f})"
            )
            hold = {action_name: [(float(start_xy[0]), float(start_xy[1]), 0.0)]}
            for _ in range(warmup):
                with self._env_lock:
                    self._last_obs, _, _, _, _ = self._env_step(robot_id, hold)

        start_dist = math.hypot(start_xy[0] - float(xy[0]), start_xy[1] - float(xy[1]))
        goal_action = {action_name: [(float(xy[0]), float(xy[1]), 0.0)]}
        dist = start_dist
        stable_finished = 0
        finished_need = max(1, int(profile.navigation_finished_stable_steps))
        settle_steps = max(0, int(profile.navigation_settle_steps))
        log_every = max(1, profile.navigation_log_interval)

        for step_i in range(max_steps):
            with self._env_lock:
                self._last_obs, _, terminated, _, _ = self._env_step(robot_id, goal_action)
            done = bool(terminated[0]) if isinstance(terminated, (list, tuple)) else bool(
                terminated
            )
            if done:
                return f"navigate terminated early: {robot_id}"
            robot_obs = self._extract_robot_obs(
                self._last_obs, robot_id=robot_id, robot_type=profile.robot_type
            )
            pos_xy = PiperGo2ManipulationRunner._xy_from_robot_position(
                robot_obs.get("position") if robot_obs else None
            )
            at_goal = False
            if pos_xy is not None:
                dist = math.hypot(pos_xy[0] - float(xy[0]), pos_xy[1] - float(xy[1]))
                at_goal = dist <= threshold
            ctrl = (
                (robot_obs.get("controllers") or {}).get(action_name) or {}
                if robot_obs
                else {}
            )
            if at_goal and bool(ctrl.get("finished")):
                stable_finished += 1
            else:
                stable_finished = 0
            if at_goal and stable_finished >= finished_need:
                self._trace(
                    f"robot={robot_id} navigate at goal (dist={dist:.4f}), "
                    f"settling {settle_steps} steps ..."
                )
                for settle_i in range(settle_steps):
                    with self._env_lock:
                        self._last_obs, _, terminated, _, _ = self._env_step(
                            robot_id, goal_action
                        )
                    term = bool(terminated[0]) if isinstance(terminated, (list, tuple)) else bool(
                        terminated
                    )
                    if term:
                        return f"navigate terminated during settle: {robot_id}"
                return (
                    f"navigate ok: {robot_id} dist={dist:.4f} "
                    f"settled={settle_steps}"
                )
            if step_i == 0 or (step_i + 1) % log_every == 0:
                self._trace(
                    f"robot={robot_id} navigate step={step_i + 1}/{max_steps} "
                    f"dist={dist:.4f} at_goal={at_goal} finished_streak={stable_finished}"
                )
        return f"navigate failed: {robot_id} dist={dist:.4f}"

    # ── Franka pick / place (arm_ik + gripper via FrankaRobot controllers) ──

    def _set_object_mass(self, object_name: str, mass: float) -> bool:
        if self._env is None:
            return False
        try:
            obj = self._env.runner.get_obj(object_name)
            obj.set_mass(float(mass))
            self._trace(f"set_mass object={object_name} mass={mass}")
            return True
        except Exception as exc:
            self._trace(f"set_mass skipped object={object_name}: {exc}")
            return False

    def _apply_merom_object_masses(self) -> str:
        """Match InternUtopia demo/test3_multi_robot_debug.py post-spawn masses."""
        applied: list[str] = []
        if self._set_object_mass("pick_cube", 0.05):
            applied.append("pick_cube=0.05")
        franka = self._robots.get("franka")
        cube_mass = float(getattr(franka, "franka_cube_mass", 0.02) if franka else 0.02)
        if self._set_object_mass("franka_pick_cube", cube_mass):
            applied.append(f"franka_pick_cube={cube_mass}")
        if self._set_object_mass("place_pedestal", 100.0):
            applied.append("place_pedestal=100")
        return ",".join(applied) if applied else "none"

    def _apply_merom_franka_rmpflow_tuning(self) -> str:
        """Apply mocap teleop Franka PD gains when RMPFlow stack is enabled."""
        franka = self._robots.get("franka")
        if franka is None or not franka.franka_use_rmpflow or self._env is None:
            return "skipped"
        try:
            task = next(iter(self._env.runner.current_tasks.values()))
            robot = task.robots.get("franka")
            if robot is None:
                return "missing_robot"
            ok = apply_mocap_franka_gains(robot.articulation)
            self._trace(f"franka rmpflow gains applied={ok}")
            return "ok" if ok else "failed"
        except Exception as exc:
            self._trace(f"franka rmpflow tuning skipped: {exc}")
            return f"skipped:{exc}"

    def _apply_franka_initial_joint_pose(self) -> str:
        """Spawn Franka in grasp-ready joint pose (matches sess_merom_franka_arm / test3)."""
        profile = self._robots.get("franka")
        if profile is None or self._env is None:
            return "skipped"
        joints = list(profile.franka_initial_joint_positions or [])
        if not joints:
            return "skipped"
        try:
            task = next(iter(self._env.runner.current_tasks.values()))
            robot = task.robots.get("franka")
            if robot is None:
                return "missing_robot"
            q = np.array(joints, dtype=float)
            art = robot.articulation
            if hasattr(art, "set_joint_positions"):
                art.set_joint_positions(q)
            elif hasattr(art, "_articulation_view"):
                art._articulation_view.set_joint_positions(q.reshape(1, -1))
            else:
                return "unsupported_articulation"
            if hasattr(art, "set_joint_velocities"):
                art.set_joint_velocities(np.zeros_like(q))
            elif hasattr(art, "_articulation_view"):
                art._articulation_view.set_joint_velocities(
                    np.zeros((1, q.size), dtype=float)
                )
            lock = franka_ik_joint_lock_action()
            n_settle = max(0, int(profile.franka_initial_settle_steps))
            for _ in range(n_settle):
                with self._env_lock:
                    self._last_obs, _, _, _, _ = self._env_step("franka", lock)
            self._trace(
                f"franka initial joints applied count={len(joints)} settle={n_settle}"
            )
            return "ok"
        except Exception as exc:
            self._trace(f"franka initial joints skipped: {exc}")
            return f"skipped:{exc}"

    def _franka_robot_obs(self, robot_id: str, profile: RobotProfile) -> dict[str, Any]:
        block = self._extract_robot_obs(
            self._last_obs, robot_id=robot_id, robot_type=profile.robot_type
        )
        return dict(block or {})

    def _get_franka_pick_place(
        self, robot_id: str, profile: RobotProfile
    ) -> FrankaPickPlaceExecutor:
        if robot_id in self._franka_pick_place:
            return self._franka_pick_place[robot_id]
        if self._env is None:
            raise RuntimeError("env not started")

        def step_fn(action: dict[str, Any]) -> tuple[dict[str, Any], bool]:
            with self._env_lock:
                self._last_obs, _, terminated, _, _ = self._env_step(robot_id, action)
            obs = self._franka_robot_obs(robot_id, profile)
            term = bool(terminated[0]) if isinstance(terminated, (list, tuple)) else bool(
                terminated
            )
            return obs, term

        def get_obs_fn() -> dict[str, Any]:
            return self._franka_robot_obs(robot_id, profile)

        use_rmpflow = bool(profile.franka_use_rmpflow)
        executor = FrankaPickPlaceExecutor(
            step_fn=step_fn,
            get_obs_fn=get_obs_fn,
            config=FrankaPickPlaceConfig(
                pause_steps=max(1, int(profile.franka_pause_steps)),
                gripper_settle_steps=max(1, int(profile.franka_gripper_settle_steps)),
                max_steps_per_phase=max(1, int(profile.franka_max_steps_per_phase)),
                arm_waypoint_count=max(1, int(profile.franka_arm_waypoint_count)),
                release_pause_steps=max(1, int(profile.franka_release_pause_steps)),
                release_waypoint_count=max(1, int(profile.franka_release_waypoint_count)),
                motion_steps_per_waypoint=max(
                    1, int(profile.franka_motion_steps_per_waypoint)
                ),
                ik_min_motion_steps=max(1, int(profile.franka_ik_min_motion_steps)),
                arm_controller=RMPFLOW_CONTROLLER if use_rmpflow else ARM_IK_CONTROLLER,
                robot_base_position=tuple(float(v) for v in profile.position),
                use_robot_base_frame=use_rmpflow,
            ),
        )
        self._franka_pick_place[robot_id] = executor
        return executor

    def _resolve_franka_target(
        self,
        profile: RobotProfile,
        kind: Literal["grasp", "place"],
        key: str,
    ) -> ManipulationTarget | str:
        registry = profile.grasp_targets if kind == "grasp" else profile.place_targets
        if key in registry:
            return coerce_manipulation_target(registry[key], default_name=key)
        if kind == "grasp":
            auto = resolve_blue_cube_grasp_target(profile.objects)
            if auto is not None:
                return coerce_manipulation_target(auto, default_name=str(auto.get("name", key)))
        return key

    def _cmd_franka_manipulation(
        self,
        robot_id: str,
        profile: RobotProfile,
        params: dict[str, Any],
        *,
        gripper_command: Literal["open", "close"],
    ) -> str:
        if profile.robot_type != "franka":
            return f"Error: franka manipulation requires robot_type=franka, got {profile.robot_type}"
        kind: Literal["grasp", "place"] = "grasp" if gripper_command == "close" else "place"
        default_key = "cube" if kind == "grasp" else "pedestal"
        key = str(
            params.get("target")
            or params.get(f"{kind}_target")
            or default_key
        ).strip()
        target = self._resolve_franka_target(profile, kind, key)
        if isinstance(target, str):
            return f"Error: unknown {kind}_target={key!r} for robot={profile.robot_id}"

        executor = self._get_franka_pick_place(robot_id, profile)
        action_name = "grasp" if gripper_command == "close" else "place"
        result = executor.pick(target) if gripper_command == "close" else executor.release(target)
        if not result.success:
            phase = result.failed_phase or "unknown"
            return f"Error: franka {action_name} failed at phase={phase}"
        return f"franka {action_name} ok: target={key}"

    def _cmd_franka_pick_place(
        self, robot_id: str, profile: RobotProfile, params: dict[str, Any]
    ) -> str:
        grasp_key = str(params.get("grasp_target") or params.get("target") or "cube")
        place_key = str(params.get("place_target") or "pedestal")
        grasp_target = self._resolve_franka_target(profile, "grasp", grasp_key)
        if isinstance(grasp_target, str):
            return f"Error: unknown grasp_target={grasp_key!r} for robot={profile.robot_id}"
        place_target = self._resolve_franka_target(profile, "place", place_key)
        if isinstance(place_target, str):
            return f"Error: unknown place_target={place_key!r} for robot={profile.robot_id}"

        executor = self._get_franka_pick_place(robot_id, profile)
        result = executor.pick_and_place(grasp_target, place_target)
        if not result.success:
            phase = result.failed_phase or result.action
            return f"Error: franka pick_place failed at phase={phase}"
        return f"franka pick_place ok: grasp={grasp_key} place={place_key}"

    def _augment_franka_action(
        self, robot_id: str, profile: RobotProfile, action: dict[str, Any]
    ) -> dict[str, Any]:
        obs = self._franka_robot_obs(robot_id, profile)
        if profile.franka_use_rmpflow:
            return augment_franka_action(
                obs,
                action,
                robot_base=profile.position,
                arm_controller=RMPFLOW_CONTROLLER,
            )
        return augment_franka_action(
            obs,
            action,
            arm_controller=ARM_IK_CONTROLLER,
        )

    def _hold_action_for_robot(
        self, robot_id: str, profile: RobotProfile
    ) -> dict[str, Any]:
        """Hold inactive robots: legged via move_to_point; Franka via joint lock / RMPFlow."""
        if profile.robot_type == "franka":
            if profile.franka_use_rmpflow:
                hold = self._augment_franka_action(robot_id, profile, {})
                return hold if hold else {}
            return franka_ik_joint_lock_action()
        action_name = str(
            profile.navigation_action_name
            or self._default_nav_action_name(profile.robot_type)
        )
        robot_obs = self._extract_robot_obs(
            self._last_obs, robot_id=robot_id, robot_type=profile.robot_type
        )
        hold_xy = PiperGo2ManipulationRunner._xy_from_robot_position(
            robot_obs.get("position") if robot_obs else None
        )
        if hold_xy is None:
            hold_xy = (float(profile.position[0]), float(profile.position[1]))
        return {action_name: [(float(hold_xy[0]), float(hold_xy[1]), 0.0)]}

    def _merge_multi_robot_action(
        self, active_robot_id: str, active_action: dict[str, Any]
    ) -> dict[str, Any]:
        merged = {active_robot_id: active_action}
        for rid, spec in self._robots.items():
            if rid == active_robot_id:
                continue
            hold = self._hold_action_for_robot(rid, spec)
            if hold:
                merged[rid] = hold
        return merged

    def _env_step(self, robot_id: str, action: dict[str, Any]) -> tuple[Any, ...]:
        assert self._env is not None
        profile = self._robots[robot_id]
        if profile.robot_type == "franka":
            action = self._augment_franka_action(robot_id, profile, action)
            if "arm_joint_controller" in action and "arm_ik_controller" not in action:
                action.pop("rmpflow_controller", None)
        return self._env.step(action=[self._merge_multi_robot_action(robot_id, action)])

    # ── PiperGo2 base freeze (arm only) ───────────────────────────────

    def _should_freeze_base(self, profile: RobotProfile, action: dict[str, Any]) -> bool:
        if profile.robot_type != "pipergo2" or not profile.freeze_base_during_arm_control:
            return False
        keys = set(action.keys())
        if not keys & set(profile.arm_control_action_names):
            return False
        nav = {
            "move_by_speed",
            "move_to_point",
            "move_along_path",
            "rotate",
            self._default_nav_action_name(profile.robot_type),
        }
        if keys & nav:
            return False
        return True

    def _init_pipergo2_freeze_view(self) -> None:
        if "pipergo2" not in self._robots:
            return
        try:
            from isaacsim.core.prims import Articulation as ArticulationView  # type: ignore
        except ImportError:
            try:
                from omni.isaac.core.articulations import ArticulationView  # type: ignore
            except ImportError:
                return
        try:
            view = ArticulationView(
                prim_paths_expr="/World/env_0/robots/pipergo2",
                name="pipergo2_freeze_view",
            )
            view.initialize()
            self._pipergo2_view = view
        except Exception as exc:
            print(f"[rollout/merom] pipergo2 freeze view init skipped: {exc}")

    def _freeze_robot_pose(self) -> None:
        if self._pipergo2_view is None:
            return
        try:
            pos, rot = self._pipergo2_view.get_world_poses()
            self._frozen_pose = (pos.copy(), rot.copy())
            self._trace("freeze pipergo2 base pose")
        except Exception as exc:
            print(f"[rollout/merom] freeze_pose failed: {exc}")

    def _apply_frozen_pose(self) -> None:
        if self._frozen_pose is None or self._pipergo2_view is None:
            return
        try:
            import numpy as np

            pos, rot = self._frozen_pose
            self._pipergo2_view.set_world_poses(pos, rot)
            self._pipergo2_view.set_linear_velocities(np.zeros((1, 3)))
            self._pipergo2_view.set_angular_velocities(np.zeros((1, 3)))
        except Exception as exc:
            print(f"[rollout/merom] apply_frozen_pose failed: {exc}")

    def _clear_frozen_pose(self) -> None:
        self._frozen_pose = None

    # ── Env build ─────────────────────────────────────────────────────

    def _build_vec_env(self, scene_asset_path: str):
        bridge = importlib.import_module("internutopia.bridge")
        objects_mod = importlib.import_module("internutopia_extension.configs.objects")
        tasks = importlib.import_module("internutopia_extension.configs.tasks")
        core_cfg = importlib.import_module("internutopia.core.config")
        vec_env = importlib.import_module("internutopia.core.vec_env")
        import_extensions = importlib.import_module("internutopia_extension").import_extensions

        Config = core_cfg.Config
        SimConfig = core_cfg.SimConfig
        Env = vec_env.Env
        SingleInferenceTaskCfg = tasks.SingleInferenceTaskCfg
        DynamicCubeCfg = objects_mod.DynamicCubeCfg
        VisualCubeCfg = objects_mod.VisualCubeCfg

        robot_cfgs: list[Any] = []
        for rid, spec in sorted(self._robots.items()):
            pos = spec.position
            if spec.robot_type == "g1":
                cfg = bridge.create_g1_robot_cfg(
                    position=pos,
                    forward_speed=spec.forward_speed,
                    rotation_speed=spec.rotation_speed,
                    rotate_speed=spec.rotate_speed,
                    move_to_point_threshold=spec.move_to_point_threshold,
                )
            elif spec.robot_type == "franka":
                if spec.franka_use_rmpflow:
                    usd = None
                    if spec.robot_usd_path:
                        usd_path = _resolve_repo_path(spec.robot_usd_path)
                        if usd_path.is_file():
                            usd = str(usd_path)
                    cfg = bridge.create_franka_rmpflow_robot_cfg(
                        position=pos,
                        usd_path=usd,
                    )
                else:
                    cfg = bridge.create_franka_robot_cfg(
                        position=pos,
                        # Merom shares one env for pick/place (IK) and arm_joint demo.
                        include_arm_joint_controller=True,
                    )
            elif spec.robot_type == "pipergo2":
                cfg = bridge.create_pipergo2_robot_cfg(
                    position=pos, arm_mass_scale=spec.arm_mass_scale
                )
            else:
                raise ValueError(f"unsupported robot_type={spec.robot_type!r}")
            if spec.robot_usd_path and not (
                spec.robot_type == "franka" and spec.franka_use_rmpflow
            ):
                usd = _resolve_repo_path(spec.robot_usd_path)
                if not usd.is_file():
                    raise FileNotFoundError(f"robot USD not found for {rid}: {usd}")
                cfg.usd_path = str(usd)
                self._trace(f"robot {rid} usd_path={usd}")
            elif spec.robot_usd_path and spec.robot_type == "franka" and spec.franka_use_rmpflow:
                self._trace(f"robot {rid} usd_path={cfg.usd_path}")
            self._apply_robot_identity(rid, spec, cfg)
            robot_cfgs.append(cfg)

        objects: list[Any] = []
        all_objects_spec = list(self._objects_spec)
        for spec in self._robots.values():
            if spec.objects:
                all_objects_spec.extend(spec.objects)
        for item in all_objects_spec:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "dynamic_cube")).strip().lower()
            cfg = {
                "name": item["name"],
                "prim_path": item["prim_path"],
                "position": tuple(float(x) for x in item["position"]),
                "scale": tuple(float(x) for x in item["scale"]),
                "color": item.get("color", (0.5, 0.5, 0.5)),
            }
            for key in ("mass", "static_friction", "dynamic_friction", "restitution"):
                if key in item and item[key] is not None:
                    cfg[key] = float(item[key])
            if kind == "visual_cube":
                cfg["color"] = list(cfg["color"])
                objects.append(VisualCubeCfg(**cfg))
            else:
                objects.append(DynamicCubeCfg(**cfg))

        headless = self._api_kwargs.pop("headless", None)
        if headless is None:
            headless = not bool(self._api_kwargs.pop("force_gui", self.gui))

        config = Config(
            simulator=SimConfig(
                physics_dt=1 / 240,
                rendering_dt=1 / 240,
                use_fabric=False,
                rendering_interval=5 if self.gui else 0,
                headless=headless,
                native=headless,
                webrtc=headless,
            ),
            env_num=1,
            metrics_save_path="none",
            task_configs=[
                SingleInferenceTaskCfg(
                    scene_asset_path=scene_asset_path,
                    robots=robot_cfgs,
                    objects=objects,
                    enable_static_scene_mesh_collision_patch=self._collision_patch,
                )
            ],
        )
        import_extensions()
        return Env(config)

    def _collision_patch_merom_scene(self) -> None:
        if self._env is None:
            return
        stage = self._env.runner._world.stage
        from pxr import PhysxSchema, Usd, UsdPhysics

        scene_root = stage.GetPrimAtPath("/World/env_0/scene")
        if not scene_root.IsValid():
            return
        for prim in Usd.PrimRange(scene_root):
            if prim.IsInstance():
                prim.SetInstanceable(False)
        for prim in Usd.PrimRange(scene_root):
            if prim.GetTypeName() != "Mesh":
                continue
            try:
                UsdPhysics.CollisionAPI.Apply(prim)
                physx = PhysxSchema.PhysxCollisionAPI.Apply(prim)
                physx.CreateApproximationAttr().Set("convexHull")
            except Exception:
                pass

    @staticmethod
    def _apply_robot_identity(rid: str, spec: RobotProfile, cfg: Any) -> None:
        """Match PhyAgentOS3 ``g1_simulation_driver`` / ``multi_robot_simulation_driver`` naming."""
        if spec.robot_type == "g1":
            cfg.name = "g1"
            cfg.prim_path = "/g1"
        elif spec.robot_type == "pipergo2":
            cfg.name = "pipergo2"
            cfg.prim_path = "/pipergo2"
        elif spec.robot_type == "franka":
            cfg.name = "franka"
            cfg.prim_path = "/franka"
        else:
            cfg.name = rid
            cfg.prim_path = f"/{rid}"

    def _post_spawn_settle(self, rb: dict[str, Any]) -> str:
        """Spawn settle: standing hold for legged robots; optional passive for others."""
        if self._env is None:
            return ""
        steps: list[str] = []
        spawn_standing = bool(rb.get("spawn_standing", True))
        n_passive = 0 if spawn_standing else max(0, int(rb.get("pre_spawn_passive_steps", 80)))
        for _ in range(n_passive):
            with self._env_lock:
                self._last_obs, _, _, _, _ = self._env.step(action=[{}])
        if n_passive:
            steps.append(f"passive:{n_passive}")

        n_hold = max(0, int(rb.get("spawn_stand_hold_steps", 90)))
        for rid, spec in sorted(self._robots.items()):
            if spec.robot_type == "franka":
                n_pause = max(0, int(spec.franka_pause_steps))
                lock = franka_ik_joint_lock_action()
                for _ in range(n_pause):
                    with self._env_lock:
                        hold = lock if not spec.franka_use_rmpflow else {}
                        self._last_obs, _, _, _, _ = self._env_step(rid, hold)
                if n_pause:
                    steps.append(f"franka_pause:{rid}:{n_pause}")
                continue
            if spec.robot_type in ("pipergo2", "g1") and spawn_standing:
                action_name = self._default_nav_action_name(spec.robot_type)
                hold_xy = (float(spec.position[0]), float(spec.position[1]))
                hold = {action_name: [(hold_xy[0], hold_xy[1], 0.0)]}
                for _ in range(n_hold):
                    with self._env_lock:
                        self._last_obs, _, _, _, _ = self._env_step(rid, hold)
                steps.append(f"spawn_stand_hold:{rid}:{n_hold}")
                continue
            n_stab = max(0, int(rb.get("stabilize_steps_per_robot", 120)))
            if n_stab <= 0:
                continue
            action_name = self._default_nav_action_name(spec.robot_type)
            hold_xy = (float(spec.position[0]), float(spec.position[1]))
            hold = {action_name: [(hold_xy[0], hold_xy[1], 0.0)]}
            for _ in range(n_stab):
                with self._env_lock:
                    self._last_obs, _, _, _, _ = self._env_step(rid, hold)
            steps.append(f"stabilize:{rid}:{n_stab}")
        return ",".join(steps)

    def _lighting_api(self) -> Any:
        """Shim so isaac_scene_bootstrap can read ``_env.runner._world.stage``."""
        if self._env is None:
            return None

        class _Shim:
            def __init__(self, vec_env: Any) -> None:
                self._env = vec_env

        return _Shim(self._env)

    def _room_bootstrap_sequence(
        self, rb: dict[str, Any], *, focus_robot_id: str
    ) -> str:
        from rollout.simulation.isaac_scene_bootstrap import (
            apply_lighting_for_mode,
            focus_viewport_on_robot,
        )

        api = self._lighting_api()
        if api is None:
            return ""
        steps: list[str] = []
        if rb.get("apply_room_lighting", True):
            try:
                mode = str(rb.get("lighting", self._room_lighting)).strip()
                steps.extend(apply_lighting_for_mode(api, mode))
            except Exception as exc:
                steps.append(f"lighting_skipped:{exc}")
        if rb.get("focus_view_on_robot", True):
            try:
                profile = self._robots.get(focus_robot_id) or next(
                    iter(self._robots.values())
                )
                if rb.get("focus_scene_overview", False):
                    xs = [p.position[0] for p in self._robots.values()]
                    ys = [p.position[1] for p in self._robots.values()]
                    zs = [p.position[2] for p in self._robots.values()]
                    focus_xy = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
                    focus_z = sum(zs) / len(zs)
                else:
                    focus_xy = (float(profile.position[0]), float(profile.position[1]))
                    focus_z = float(profile.position[2])
                focus_viewport_on_robot(
                    focus_xy,
                    focus_z,
                    camera_eye_offset=self._camera_eye_offset,
                    camera_target_z_offset=self._camera_target_z_offset,
                    camera_target_min_z=self._camera_target_min_z,
                )
                steps.append(f"viewport_focus:{focus_robot_id}")
            except Exception as exc:
                steps.append(f"viewport_focus_skipped:{exc}")
        return ",".join(steps)

    def _verify_spawned_robots(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if self._env is None:
            return {"env": "not_started"}
        try:
            stage = self._env.runner._world.stage
            for rid in sorted(self._robots):
                path = f"/World/env_0/robots/{rid}"
                prim = stage.GetPrimAtPath(path)
                out[rid] = "ok" if prim.IsValid() else f"missing:{path}"
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}
        return out

    def _idle_step_if_due(self) -> None:
        if not self._idle_step_enabled or self._env is None:
            return
        now = time.monotonic()
        if now - self._last_idle_step_ts < self._idle_step_interval_s:
            return
        self._last_idle_step_ts = now
        hold_all: dict[str, dict[str, Any]] = {}
        for rid, spec in self._robots.items():
            hold = self._hold_action_for_robot(rid, spec)
            if hold:
                hold_all[rid] = hold
        if not hold_all:
            return
        with self._env_lock:
            try:
                self._last_obs, _, _, _, _ = self._env.step(action=[hold_all])
            except Exception:
                pass

    # ── Parsing / helpers ─────────────────────────────────────────────

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value is None:
            return None
        return float(value)

    @staticmethod
    def _parse_robots(raw: dict[str, Any]) -> dict[str, RobotProfile]:
        out: dict[str, RobotProfile] = {}
        for rid, block in raw.items():
            if not isinstance(block, dict):
                continue
            robot_id = str(rid).strip()
            rtype = str(block.get("type", block.get("robot_type", "pipergo2"))).strip().lower()
            pos_raw = block.get("position", block.get("robot_start", (0.0, 0.0, 0.55)))
            pos = tuple(float(x) for x in pos_raw[:3])
            wp = PiperGo2ManipulationRunner._normalize_waypoints(block.get("waypoints", {}))
            aliases = PiperGo2ManipulationRunner._normalize_aliases(
                block.get("waypoint_aliases", {})
            )
            arm_names = block.get("arm_control_action_names")
            if isinstance(arm_names, list):
                arm_list = [str(n) for n in arm_names if str(n).strip()]
            elif rtype == "franka":
                arm_list = [
                    "arm_ik_controller",
                    "gripper_controller",
                    "arm_joint_controller",
                ]
            else:
                arm_list = ["arm_joint_controller", "arm_ik_controller"]
            raw_objects = block.get("objects")
            obj_list = [o for o in raw_objects if isinstance(o, dict)] if isinstance(
                raw_objects, list
            ) else []
            grasp_raw = block.get("grasp_targets")
            grasp = (
                {str(k): dict(v) for k, v in grasp_raw.items() if isinstance(v, dict)}
                if isinstance(grasp_raw, dict)
                else {}
            )
            place_raw = block.get("place_targets")
            place = (
                {str(k): dict(v) for k, v in place_raw.items() if isinstance(v, dict)}
                if isinstance(place_raw, dict)
                else {}
            )
            usd_path = str(block.get("robot_usd_path", block.get("usd_path", ""))).strip()
            out[robot_id] = RobotProfile(
                robot_id=robot_id,
                robot_type=rtype,
                position=pos,
                waypoints=wp,
                waypoint_aliases=aliases,
                robot_usd_path=usd_path,
                navigation_max_steps=int(block.get("navigation_max_steps", 1200)),
                navigation_threshold=float(block.get("navigation_threshold", 0.10)),
                navigation_warmup_steps=int(block.get("navigation_warmup_steps", 90)),
                navigation_finished_stable_steps=max(
                    1, int(block.get("navigation_finished_stable_steps", 15))
                ),
                navigation_settle_steps=max(
                    0, int(block.get("navigation_settle_steps", 60))
                ),
                navigation_log_interval=max(
                    1, int(block.get("navigation_log_interval", 100))
                ),
                navigation_action_name=block.get("navigation_action_name"),
                arm_mass_scale=float(block.get("arm_mass_scale", 0.25)),
                freeze_base_during_arm_control=bool(
                    block.get("freeze_base_during_arm_control", True)
                ),
                arm_control_action_names=arm_list,
                objects=obj_list,
                grasp_targets=grasp,
                place_targets=place,
                franka_pause_steps=int(block.get("franka_pause_steps", 45)),
                franka_gripper_settle_steps=int(block.get("franka_gripper_settle_steps", 30)),
                franka_max_steps_per_phase=int(block.get("franka_max_steps_per_phase", 1500)),
                franka_arm_waypoint_count=int(block.get("franka_arm_waypoint_count", 24)),
                franka_release_pause_steps=int(block.get("franka_release_pause_steps", 150)),
                franka_release_waypoint_count=int(
                    block.get("franka_release_waypoint_count", 24)
                ),
                franka_motion_steps_per_waypoint=int(
                    block.get("franka_motion_steps_per_waypoint", 180)
                ),
                franka_ik_min_motion_steps=int(
                    block.get("franka_ik_min_motion_steps", 30)
                ),
                franka_cube_mass=float(block.get("franka_cube_mass", 0.02)),
                franka_use_rmpflow=bool(block.get("franka_use_rmpflow", False)),
                franka_initial_joint_positions=list(
                    block.get("franka_initial_joint_positions")
                    or DEFAULT_FRANKA_HOME_JOINTS
                ),
                franka_initial_settle_steps=int(
                    block.get("franka_initial_settle_steps", 60)
                ),
                include_arm_joint_controller=bool(
                    block.get("include_arm_joint_controller", False)
                ),
                forward_speed=MeromMultiRobotRunner._optional_float(
                    block.get("forward_speed")
                ),
                rotation_speed=MeromMultiRobotRunner._optional_float(
                    block.get("rotation_speed")
                ),
                rotate_speed=MeromMultiRobotRunner._optional_float(
                    block.get("rotate_speed")
                ),
                move_to_point_threshold=MeromMultiRobotRunner._optional_float(
                    block.get("move_to_point_threshold")
                ),
            )
        return out

    @staticmethod
    def _resolve_waypoint_key(profile: RobotProfile, key: str) -> str:
        k = key.strip()
        for canon in profile.waypoints:
            if canon.lower() == k.lower():
                return canon
        alias = profile.waypoint_aliases.get(k.lower())
        if alias:
            for canon in profile.waypoints:
                if canon.lower() == alias.strip().lower():
                    return canon
        return k

    @staticmethod
    def _default_nav_action_name(robot_type: str) -> str:
        if robot_type == "g1":
            rob = importlib.import_module("internutopia_extension.configs.robots.g1")
            return rob.move_to_point_cfg.name
        rob = importlib.import_module("internutopia_extension.configs.robots.pipergo2")
        return rob.move_to_point_cfg.name

    @staticmethod
    def _extract_robot_obs(
        obs_data: Any, *, robot_id: str, robot_type: str
    ) -> dict[str, Any] | None:
        if isinstance(obs_data, dict):
            if robot_id in obs_data and isinstance(obs_data[robot_id], dict):
                return obs_data[robot_id]
            if robot_type in obs_data and isinstance(obs_data[robot_type], dict):
                return obs_data[robot_type]
            if "position" in obs_data:
                return obs_data
        if isinstance(obs_data, (list, tuple)) and obs_data:
            first = obs_data[0]
            if isinstance(first, dict):
                if robot_id in first and isinstance(first[robot_id], dict):
                    return first[robot_id]
                if robot_type in first and isinstance(first[robot_type], dict):
                    return first[robot_type]
                if "position" in first:
                    return first
        return None

    @staticmethod
    def _trace(msg: str) -> None:
        print(f"[rollout/merom] {msg}", flush=True)

    def _to_builtin(self, value: Any) -> Any:
        try:
            mod = importlib.import_module("internutopia.bridge.atomic_actions")
            return mod._to_builtin(value)
        except Exception:
            return json.loads(json.dumps(value, default=str))

    @staticmethod
    def _safe_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        return {"raw": str(value)}
