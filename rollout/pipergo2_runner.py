"""
PiperGo2 manipulation rollout runner.

Migrated from ``hal/drivers/pipergo2_manipulation_driver.py`` for the external
``rollout`` WebSocket service. Returns structured dicts instead of ACTION.md
strings.
"""

from __future__ import annotations

import importlib
import json
import math
import sys
import threading
import time
from pathlib import Path
from typing import Any

from rollout.bootstrap import REPO_ROOT, ensure_bundled_internutopia


def _resolve_repo_path(path: str | Path) -> Path:
    """Resolve config paths relative to the PhyAgentOS repo root."""
    p = Path(path).expanduser()
    if p.is_absolute():
        return p.resolve()
    return (REPO_ROOT / p).resolve()


def normalize_control_action(action: dict[str, Any]) -> dict[str, Any]:
    """Normalize rollout control dicts to internutopia controller shapes.

    - ``move_by_speed``: flat 3-vector ``[forward, lateral, rotation]`` (not ``[[...]]``).
    - ``move_to_point``: list of one goal ``[(x, y, z)]`` (unchanged).
    """
    out: dict[str, Any] = {}
    for name, value in action.items():
        if name == "move_by_speed":
            out[name] = _normalize_move_by_speed(value)
        else:
            out[name] = value
    return out


def _normalize_move_by_speed(value: Any) -> list[float]:
    """Accept ``[vx, vy, wz]`` or legacy ``[[vx, vy, wz]]`` from session YAML."""
    if isinstance(value, (list, tuple)) and len(value) == 1:
        inner = value[0]
        if isinstance(inner, (list, tuple)) and len(inner) == 3:
            return [float(inner[0]), float(inner[1]), float(inner[2])]
    if isinstance(value, (list, tuple)) and len(value) == 3:
        if not isinstance(value[0], (list, tuple)):
            return [float(value[0]), float(value[1]), float(value[2])]
    raise ValueError(
        "move_by_speed expects [forward, lateral, rotation] "
        f"(3 floats), got {value!r}"
    )


class PiperGo2ManipulationRunner:
    """InternUtopia PiperGo2 manipulation env lifecycle for rollout WS."""

    def __init__(self, config: dict[str, Any], *, gui: bool = False) -> None:
        self.config = dict(config)
        self.gui = bool(gui)
        self._api = None
        self._env = None
        self._env_lock = threading.RLock()
        self._last_obs: Any = None
        self._started = False

        self._scene_asset_path = str(config.get("scene_asset_path", "")).strip()
        self._robot_start = tuple(config.get("robot_start", (0.0, 0.0, 0.55)))
        self._arm_mass_scale = float(config.get("arm_mass_scale", 1.0))
        self._robot_usd_path = str(config.get("robot_usd_path", "")).strip()
        self._objects_spec = list(config.get("objects", []))
        self._api_kwargs = dict(config.get("api_kwargs", {}))
        self._api_kwargs["force_gui"] = self.gui
        self._api_kwargs.pop("headless", None)
        self._isaac_env_cfg = config.get("isaac_env")

        self._waypoints = self._normalize_waypoints(config.get("waypoints", {}))
        self._waypoint_aliases = self._normalize_aliases(config.get("waypoint_aliases", {}))
        self._navigation_action_name = config.get("navigation_action_name")
        self._navigation_max_steps = int(config.get("navigation_max_steps", 1200))
        self._navigation_threshold = float(config.get("navigation_threshold", 0.10))
        self._navigation_warmup_steps = int(
            config.get("navigation_warmup_steps", config.get("api_kwargs", {}).get("pause_steps", 90))
        )
        self._navigation_log_interval = max(1, int(config.get("navigation_log_interval", 100)))
        self._navigation_finished_stable_steps = max(
            1, int(config.get("navigation_finished_stable_steps", 15))
        )
        self._navigation_settle_steps = max(0, int(config.get("navigation_settle_steps", 60)))

        self._visible_objects = list(config.get("visible_objects", []))
        pp = config.get("pick_place") or {}
        self._pick_target_raw = dict(pp.get("pick_target", {}))
        self._place_target_raw = dict(pp.get("place_target", {}))
        self._pick_place_output_dir = str(pp.get("output_dir", "/tmp/paos_pipergo2_logs"))
        self._pick_dump_name = str(pp.get("pick_dump", "room_pick.json"))
        self._place_dump_name = str(pp.get("place_dump", "room_place.json"))

        self._room_bootstrap = dict(config.get("room_bootstrap", {}))
        self._pp_defaults = dict(config.get("pick_place_defaults", {}))
        self._scene_narration_cn = ""
        self._last_pick_place_summary = ""
        # Bundled InternUtopia lives under rollout/vendor/ (no external checkout).
        ensure_bundled_internutopia()

        self._idle_step_enabled = bool(config.get("idle_step_enabled", True))
        self._idle_steps_per_cycle = int(
            config.get("idle_steps_per_cycle", config.get("idle_steps_per_poll", 1))
        )
        self._idle_step_interval_s = float(config.get("idle_step_interval_s", 1.0 / 30.0))
        self._last_idle_step_ts = 0.0
        self._room_lighting = str(config.get("room_lighting", "grey_studio")).strip().lower()
        self._camera_eye_offset = tuple(config.get("camera_eye_offset", (-2.8, -2.2, 1.8)))
        self._camera_target_z_offset = float(config.get("camera_target_z_offset", -0.4))
        self._camera_target_min_z = float(config.get("camera_target_min_z", 0.2))
        self._eef_live_marker_enabled = bool(config.get("eef_live_marker_enabled", False))
        self._vla_cfg: dict[str, Any] = dict(config.get("vla", {}) or {})
        self._vla_session: dict[str, Any] | None = None
        self._freeze_base_during_arm_control = bool(
            config.get("freeze_base_during_arm_control", True)
        )
        raw_arm_names = config.get(
            "arm_control_action_names",
            ["arm_joint_controller", "arm_ik_controller"],
        )
        if isinstance(raw_arm_names, (list, tuple)):
            self._arm_control_action_names = [str(n) for n in raw_arm_names if str(n).strip()]
        else:
            self._arm_control_action_names = ["arm_joint_controller"]
        if not self._arm_control_action_names:
            self._arm_control_action_names = ["arm_joint_controller"]

    # ── Public rollout API ─────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        return {
            "runner": "pipergo2_manipulation",
            "started": self._started,
            "has_api": self._api is not None,
            "has_env": self._env is not None,
        }

    def reset(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        if self._started and self._api is not None and not payload.get("force", False):
            return {
                "obs": self.build_observation(),
                "info": {"message": "already_started", "reused": True},
            }

        if self._api is not None:
            self.close()

        if self.gui and self._isaac_env_cfg:
            try:
                from rollout.simulation.isaac_bootstrap import bootstrap_isaac_env

                bootstrap_isaac_env(self._isaac_env_cfg, want_gui=True)
            except Exception as exc:
                print(f"[rollout/pipergo2] WARNING: isaac bootstrap skipped: {exc}")

        scene_asset_path = str(payload.get("scene_asset_path", self._scene_asset_path)).strip()
        if not scene_asset_path:
            raise ValueError("missing scene_asset_path in config or reset payload")
        scene_path = _resolve_repo_path(scene_asset_path)
        if not scene_path.exists():
            raise FileNotFoundError(f"scene file not found: {scene_path}")

        robot_start = payload.get("robot_start", list(self._robot_start))
        arm_mass_scale = float(payload.get("arm_mass_scale", self._arm_mass_scale))
        robot_usd_path = str(_resolve_repo_path(payload.get("robot_usd_path", self._robot_usd_path)))
        objects_spec = payload.get("objects", self._objects_spec)
        api_kwargs = dict(self._api_kwargs)
        api_kwargs.update(payload.get("api_kwargs", {}))

        self._api = self._build_api(
            scene_asset_path=str(scene_path),
            robot_start=robot_start,
            arm_mass_scale=arm_mass_scale,
            robot_usd_path=robot_usd_path,
            objects_spec=objects_spec,
            api_kwargs=api_kwargs,
        )
        self._last_obs = self._api.start()
        if not bool(payload.get("eef_live_marker_enabled", self._eef_live_marker_enabled)):
            self._disable_api_eef_live_marker()
        self._env = getattr(self._api, "_env", None)
        if isinstance(robot_start, list) and len(robot_start) >= 3:
            self._robot_start = tuple(float(x) for x in robot_start[:3])

        rb = dict(self._room_bootstrap)
        rb.update(payload.get("room_bootstrap") or {})
        boot_info: dict[str, Any] = {}
        if rb.get("enabled", True) and not payload.get("skip_room_bootstrap"):
            boot_info["bootstrap"] = self._room_bootstrap_sequence(rb)
        self._rebuild_scene_narration()
        vla_msg = self._maybe_preheat_vla_session()
        if vla_msg:
            boot_info["vla_preheat"] = vla_msg

        self._started = True
        return {
            "obs": self.build_observation(),
            "info": {
                "message": "started",
                "scene_asset_path": str(scene_path),
                **boot_info,
            },
        }

    def observe(self) -> dict[str, Any]:
        if not self._started or self._env is None:
            raise RuntimeError("rollout not started; call reset first")
        self._idle_step_if_due()
        return self.build_observation()

    def step(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._started or self._env is None:
            raise RuntimeError("rollout not started; call reset first")

        mode = str(payload.get("mode", "control")).strip().lower()
        if mode == "control":
            action = payload.get("action", {})
            if not isinstance(action, dict):
                raise ValueError("control step requires payload.action dict")
            action = normalize_control_action(action)
            sim_steps = int(payload.get("sim_steps", payload.get("repeat", 1)))
            if sim_steps < 1:
                sim_steps = 1
            freeze_base = self._should_freeze_base_for_control(action)
            self._trace(
                f"step control keys={list(action.keys())} sim_steps={sim_steps} "
                f"freeze_base={freeze_base}"
            )
            if freeze_base:
                self._freeze_robot_base()
            reward = 0.0
            info: dict[str, Any] = {}
            done = False
            try:
                for sim_i in range(sim_steps):
                    with self._env_lock:
                        self._last_obs, reward, terminated, truncated, info = self._env.step(
                            action=action
                        )
                    if freeze_base:
                        self._apply_frozen_robot_base()
                    done = bool(terminated) if not isinstance(terminated, (list, tuple)) else bool(
                        terminated[0]
                    )
                    if done:
                        self._trace(
                            f"control terminated early at sim_step={sim_i + 1}/{sim_steps}"
                        )
                        break
            finally:
                if freeze_base:
                    self._unfreeze_robot_base()
            return {
                "obs": self.build_observation(),
                "reward": float(reward) if isinstance(reward, (int, float)) else 0.0,
                "done": done,
                "info": {
                    **self._safe_dict(info),
                    "sim_steps": sim_steps,
                    "sim_steps_executed": sim_i + 1,
                },
            }

        if mode == "command":
            command = str(payload.get("command", "")).strip()
            params = dict(payload.get("params") or {})
            self._trace(f"step command={command!r} params={params}")
            message = self._dispatch_command(command, params)
            success = not (
                message.startswith("Error:")
                or message.startswith("navigate failed")
                or "FAILED" in message
            )
            return {
                "obs": self.build_observation(),
                "reward": 1.0 if success else 0.0,
                "done": False,
                "info": {"command": command, "message": message, "success": success},
            }

        if mode == "language":
            text = str(payload.get("text", "")).strip()
            if not text:
                raise ValueError("language step requires payload.text")
            self._trace(f"step language text={text!r}")
            return self.step({"mode": "command", "command": "language", "params": {"text": text}})

        raise ValueError(f"unsupported step mode: {mode}")

    def close(self) -> dict[str, Any]:
        if self._api is None:
            self._started = False
            return {"info": {"message": "already_closed"}}
        self._unfreeze_robot_base()
        try:
            self._api.close()
        finally:
            self._api = None
            self._env = None
            self._vla_session = None
            self._started = False
        return {"info": {"message": "closed"}}

    def build_observation(self) -> dict[str, Any]:
        raw = self._to_builtin(self._last_obs)
        robot = self._extract_robot_obs(self._last_obs)
        robot_xy = self._xy_from_robot_position(robot.get("position") if robot else None)
        if robot_xy is None:
            robot_xy = (float(self._robot_start[0]), float(self._robot_start[1]))

        obs: dict[str, Any] = {
            "raw": raw,
            "robot": self._to_builtin(robot) if robot else None,
            "robot_xy": [float(robot_xy[0]), float(robot_xy[1])],
            "runtime": self._runtime_snapshot(),
            "scene_description_cn": self._scene_narration_cn,
        }
        images = self._collect_vla_images()
        if images:
            obs["images"] = images
        state7 = self._read_vla_state7()
        if state7 is not None:
            obs["state"] = state7
        return obs

    # ── Command dispatch (legacy ACTION.md actions) ────────────────────

    def _dispatch_command(self, command: str, params: dict[str, Any]) -> str:
        handlers = {
            "navigate_to_waypoint": self._cmd_navigate_to_waypoint,
            "navigate_to_named": self._cmd_navigate_to_named,
            "describe_visible_scene": self._cmd_describe_visible_scene,
            "run_pick_place": self._cmd_run_pick_place,
            "run_vla_pick_and_return": self._cmd_run_vla_pick_and_return,
            "api_call": self._cmd_api_call,
            "language": self._cmd_language,
        }
        handler = handlers.get(command)
        if handler is None:
            return f"Error: unknown command: {command}"
        try:
            return handler(params)
        except Exception as exc:
            import traceback

            print(f"[rollout/pipergo2] command {command!r} failed:", flush=True)
            traceback.print_exc()
            return f"Error: {type(exc).__name__}: {exc}"

    @staticmethod
    def _trace(msg: str) -> None:
        print(f"[rollout/pipergo2] {msg}", flush=True)

    def _cmd_language(self, params: dict[str, Any]) -> str:
        """Route simple natural-language intents to structured commands."""
        text = str(params.get("text", "")).strip().lower()
        self._trace(f"language: {text!r}")
        if not text:
            return "Error: empty language text"
        if any(k in text for k in ("pick", "grasp", "抓", "捡")):
            if "vla" in text or self._vla_cfg:
                return self._cmd_run_vla_pick_and_return({"task_text": params.get("text", text)})
            return self._cmd_run_pick_place(params)
        # Do not match bare "table" — phrases like "on the table" are descriptive, not navigation.
        if any(k in text for k in ("desk", "桌", "staging")) or (
            "table" in text
            and any(h in text for h in ("go to", "navigate", "move to", "走到", "去", "前往"))
        ):
            self._trace("language -> navigate_to_named(waypoint_key=desk)")
            return self._cmd_navigate_to_named({"waypoint_key": "desk", **params})
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
            self._trace("language -> navigate_to_named(waypoint_key=home)")
            return self._cmd_navigate_to_named({"waypoint_key": "home", **params})
        return self._cmd_describe_visible_scene(params)

    def _cmd_navigate_to_named(self, params: dict[str, Any]) -> str:
        raw_key = str(params.get("waypoint_key") or params.get("target") or "").strip()
        if not raw_key:
            return "Error: waypoint_key or target is required"
        key = self._resolve_waypoint_key(raw_key)
        wp = self._waypoints.get(key)
        if not wp:
            return f"Error: unknown waypoint_key={raw_key!r}"
        goal = [float(wp[0]), float(wp[1])]
        self._trace(f"navigate_to_named: key={key!r} goal_xy={goal}")
        return self._navigate_xy(
            goal,
            max_steps=int(params.get("max_steps", self._navigation_max_steps)),
            threshold=float(params.get("threshold", self._navigation_threshold)),
        )

    def _cmd_navigate_to_waypoint(self, params: dict[str, Any]) -> str:
        waypoint = params.get("waypoint_xy")
        if not (isinstance(waypoint, list) and len(waypoint) >= 2):
            return "Error: waypoint_xy must be [x, y]"
        return self._navigate_xy(
            [float(waypoint[0]), float(waypoint[1])],
            max_steps=int(params.get("max_steps", self._navigation_max_steps)),
            threshold=float(params.get("threshold", self._navigation_threshold)),
            action_name_override=(str(params["action_name"]) if params.get("action_name") else None),
        )

    def _cmd_describe_visible_scene(self, _params: dict[str, Any]) -> str:
        self._rebuild_scene_narration()
        return f"scene_description: {self._scene_narration_cn}"

    def _cmd_api_call(self, params: dict[str, Any]) -> str:
        if self._api is None:
            return "Error: API not started"
        method_name = str(params.get("method", "")).strip()
        if not method_name:
            return "Error: params.method is required"
        method = getattr(self._api, method_name, None)
        if method is None or not callable(method):
            return f"Error: method not found: {method_name}"
        args = params.get("args", [])
        kwargs = params.get("kwargs", {})
        if not isinstance(args, list):
            return "Error: params.args must be a list"
        if not isinstance(kwargs, dict):
            return "Error: params.kwargs must be a dict"
        result = method(*args, **kwargs)
        return f"api_call ok: {method_name} => {self._safe_json(result)}"

    def _cmd_run_pick_place(self, params: dict[str, Any]) -> str:
        if self._api is None:
            return "Error: API not started"
        defaults = dict(self._pp_defaults)
        execute_place = bool(params.get("execute_place", defaults.get("default_execute_place", True)))
        return_home = bool(params.get("return_home_after_place", defaults.get("return_home_after_place", False)))
        navigate_after_pick = bool(
            params.get("navigate_after_pick", defaults.get("navigate_to_place_pedestal_after_pick", False))
        )
        hint = self._normalize_color_hint(params.get("target_color_cn", "") or params.get("color_hint", ""))
        keywords = [self._normalize_color_hint(x) for x in defaults.get("primary_pick_color_keywords", ["red"])]
        if hint and not any(k in hint for k in keywords):
            return f"Error: pick hint {hint!r} does not match keywords {keywords}"

        pick_target = self._tupleize_grasp_dict(self._pick_target_raw)
        place_target = self._tupleize_grasp_dict(self._place_target_raw)
        if not pick_target or not pick_target.get("position"):
            return "Error: pick_place.pick_target missing in config"

        out_dir = Path(str(params.get("output_dir", self._pick_place_output_dir)))
        out_dir.mkdir(parents=True, exist_ok=True)
        pick_path = out_dir / str(params.get("pick_dump", self._pick_dump_name))
        pick_result = self._api.pick(pick_target, dump_path=pick_path)
        pick_ok = self._result_ok(pick_result)
        lines = [f"pick success={pick_ok} steps={self._result_steps(pick_result)}"]
        if execute_place and pick_ok:
            if not place_target or not place_target.get("position"):
                return "Error: execute_place true but place_target missing"
            place_path = out_dir / str(params.get("place_dump", self._place_dump_name))
            place_result = self._api.release(place_target, dump_path=place_path)
            lines.append(
                f"place success={self._result_ok(place_result)} steps={self._result_steps(place_result)}"
            )
        elif navigate_after_pick and pick_ok:
            nav_xy_raw = params.get("navigate_after_pick_xy") or defaults.get("navigate_after_pick_xy")
            nav_xy = None
            if isinstance(nav_xy_raw, (list, tuple)) and len(nav_xy_raw) >= 2:
                nav_xy = [float(nav_xy_raw[0]), float(nav_xy_raw[1])]
            elif place_target and place_target.get("position"):
                nav_xy = [float(place_target["position"][0]), float(place_target["position"][1])]
            if nav_xy:
                lines.append(
                    self._navigate_xy(
                        nav_xy,
                        max_steps=self._navigation_max_steps,
                        threshold=self._navigation_threshold,
                    )
                )
        elif not execute_place:
            lines.append("place skipped (execute_place=false)")
        if return_home and self._waypoints.get("robot_home"):
            home = self._waypoints["robot_home"]
            lines.append(
                self._navigate_xy(
                    [float(home[0]), float(home[1])],
                    max_steps=self._navigation_max_steps,
                    threshold=self._navigation_threshold,
                )
            )
        self._last_pick_place_summary = "；".join(lines)
        return self._last_pick_place_summary

    def _cmd_run_vla_pick_and_return(self, params: dict[str, Any]) -> str:
        if self._api is None or self._env is None:
            return "Error: API not started"
        cfg = dict(self._vla_cfg)
        cfg.update({k: v for k, v in params.items() if k != "action_type"})
        if params.get("task_text"):
            cfg["task_text"] = str(params["task_text"])

        pick_target_prim_path = str(cfg.get("pick_target_prim_path", "/World/pick_cube"))
        pick_nav_offset = float(cfg.get("pick_nav_offset", 0.41))
        approach_xy = self._resolve_approach_xy(pick_target_prim_path, pick_nav_offset)
        if approach_xy is None:
            return f"Error: could not resolve approach xy for {pick_target_prim_path!r}"

        live_xy = None
        try:
            robot_obs = self._extract_robot_obs(self._last_obs)
            if robot_obs:
                live_xy = self._xy_from_robot_position(robot_obs.get("position"))
        except Exception:
            live_xy = None
        warmup_xy = live_xy or (float(self._robot_start[0]), float(self._robot_start[1]))
        err = self._ensure_vla_cameras(cfg, warmup_xy)
        if err:
            return err
        err = self._ensure_vla_controller(cfg)
        if err:
            return err
        session = self._vla_session
        assert session is not None

        from rollout.simulation import vla_pick as _vla

        approach_msg = self._navigate_xy(
            [approach_xy[0], approach_xy[1]],
            max_steps=int(cfg.get("approach_max_steps", self._navigation_max_steps)),
            threshold=float(cfg.get("approach_threshold", self._navigation_threshold)),
        )
        if approach_msg.startswith("navigate failed") or approach_msg.startswith("Error"):
            return f"Error: approach failed: {approach_msg}"

        action_name = self._resolve_nav_action_name()
        arm_action_name = str(session["arm_action_name"])
        hold_action_pick = {action_name: [(float(approach_xy[0]), float(approach_xy[1]), 0.0)]}
        live_hold = session.get("live_hold")
        if isinstance(live_hold, dict):
            live_hold["action"] = dict(hold_action_pick)

        result = _vla.execute_pick(
            controller=session["controller"],
            env=self._env,
            env_lock=self._env_lock,
            nav_action_name=action_name,
            arm_action_name=arm_action_name,
            hold_action=hold_action_pick,
            read_arm8=lambda: _vla.read_piper_arm8(session["robot_view"], session["joint_indices"]),
            read_cube_z=lambda: _vla.read_cube_world_z(
                self._env, session["stage"], pick_target_prim_path
            ),
            hold_xy=approach_xy,
            max_ticks=int(cfg.get("max_ticks", 30)),
            lift_threshold=float(cfg.get("cube_lift_threshold", 0.07)),
            sim_steps_per_action=int(session["sim_steps_per_action"]),
            close_gripper_ramp_ticks=int(cfg.get("close_gripper_ramp_ticks", 8)),
            close_gripper_hold_sim_steps=int(cfg.get("close_gripper_hold_sim_steps", 60)),
            max_per_tick_delta_gripper=float(cfg.get("max_per_tick_delta_gripper", 0.06)),
            dump_root=str(cfg.get("dump_root")) if cfg.get("dump_root") else None,
            dump_every=int(cfg.get("dump_every", 1)),
        )
        prefix = "vla pick SUCCESS" if result.get("success") else "Error: vla pick FAILED"
        return f"{prefix} ticks={result.get('ticks_used')} terminate={result.get('terminate')}"

    # ── Internals (ported from driver) ─────────────────────────────────

    def _runtime_snapshot(self) -> dict[str, Any]:
        live_xy = self._xy_from_robot_position(
            (self._extract_robot_obs(self._last_obs) or {}).get("position")
        )
        if live_xy is None:
            live_xy = (float(self._robot_start[0]), float(self._robot_start[1]))
        return {
            "location": "sim",
            "state": "running" if self._api is not None else "idle",
            "robot_xy": [float(live_xy[0]), float(live_xy[1])],
            "waypoint_keys": sorted(self._waypoints.keys()),
            "waypoint_aliases": dict(self._waypoint_aliases),
            "table_summary_cn": self._scene_narration_cn,
            "last_pick_place_cn": self._last_pick_place_summary,
        }

    @staticmethod
    def _normalize_waypoints(raw: Any) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        if not isinstance(raw, dict):
            return out
        for k, v in raw.items():
            key = str(k).strip()
            if key and isinstance(v, (list, tuple)) and len(v) >= 2:
                out[key] = [float(v[0]), float(v[1])]
        return out

    @staticmethod
    def _normalize_aliases(raw: Any) -> dict[str, str]:
        out: dict[str, str] = {}
        if not isinstance(raw, dict):
            return out
        for k, v in raw.items():
            a, t = str(k).strip().lower(), str(v).strip()
            if a and t:
                out[a] = t
        return out

    def _resolve_nav_action_name(self) -> str:
        if self._navigation_action_name:
            return str(self._navigation_action_name)
        ensure_bundled_internutopia()
        rob = importlib.import_module("internutopia_extension.configs.robots.pipergo2")
        return rob.move_to_point_cfg.name

    def _navigation_control_names(self) -> set[str]:
        return {
            "move_by_speed",
            "move_to_point",
            "move_along_path",
            "rotate",
            self._resolve_nav_action_name(),
        }

    def _should_freeze_base_for_control(self, action: dict[str, Any]) -> bool:
        if not self._freeze_base_during_arm_control or self._api is None:
            return False
        keys = set(action.keys())
        if not keys & set(self._arm_control_action_names):
            return False
        if keys & self._navigation_control_names():
            return False
        return True

    def _freeze_robot_base(self) -> None:
        freeze = getattr(self._api, "_freeze_robot_pose", None)
        if callable(freeze):
            freeze()
            self._trace("freeze robot base for arm control")

    def _apply_frozen_robot_base(self) -> None:
        apply_fn = getattr(self._api, "_apply_frozen_pose", None)
        if callable(apply_fn):
            apply_fn()

    def _unfreeze_robot_base(self) -> None:
        clear = getattr(self._api, "_clear_frozen_pose", None)
        if callable(clear):
            clear()

    def _maybe_preheat_vla_session(self) -> str:
        if not self._vla_cfg or not self._vla_cfg.get("attach_on_start", True):
            return ""
        if not self._vla_cfg.get("cameras"):
            return ""
        hold_xy = (float(self._robot_start[0]), float(self._robot_start[1]))
        err = self._ensure_vla_cameras(self._vla_cfg, hold_xy)
        return "" if err is None else f"skipped:{err}"

    def _disable_api_eef_live_marker(self) -> None:
        if self._api is None:
            return
        try:
            setattr(self._api, "_update_eef_debug_marker", lambda _obs: None)
        except Exception:
            pass

    def _room_bootstrap_sequence(self, rb: dict[str, Any]) -> str:
        from rollout.simulation.isaac_scene_bootstrap import apply_lighting_for_mode, focus_viewport_on_robot

        if self._api is None or self._env is None:
            return ""
        steps: list[str] = []
        if rb.get("apply_room_lighting", True):
            try:
                mode = str(rb.get("lighting", self._room_lighting)).strip()
                steps.extend(apply_lighting_for_mode(self._api, mode))
            except Exception as exc:
                steps.append(f"lighting_skipped:{exc}")
        if rb.get("focus_view_on_robot", True):
            try:
                focus_viewport_on_robot(
                    (float(self._robot_start[0]), float(self._robot_start[1])),
                    float(self._robot_start[2]),
                    camera_eye_offset=self._camera_eye_offset,
                    camera_target_z_offset=self._camera_target_z_offset,
                    camera_target_min_z=self._camera_target_min_z,
                )
                steps.append("viewport_focus")
            except Exception as exc:
                steps.append(f"viewport_focus_skipped:{exc}")
        if rb.get("collision_patch", True):
            try:
                self._collision_patch_merom_scene()
                steps.append("collision_patch")
            except Exception as exc:
                steps.append(f"collision_patch_skipped:{exc}")
        masses = rb.get("set_masses") or {}
        if isinstance(masses, dict):
            for name, mass in masses.items():
                try:
                    obj = self._api._env.runner.get_obj(str(name))
                    obj.set_mass(float(mass))
                    steps.append(f"mass:{name}")
                except Exception:
                    pass
        spawn_standing = bool(rb.get("spawn_standing", rb.get("skip_passive_spawn", True)))
        if spawn_standing:
            n_prev = int(rb.get("scene_preview_steps", 0))
        else:
            n_prev = int(rb.get("scene_preview_steps", 240))
        for _ in range(max(0, n_prev)):
            with self._env_lock:
                self._last_obs, _, _, _, _ = self._env.step({})
        if n_prev:
            steps.append(f"preview_steps:{n_prev}")

        if spawn_standing:
            n_hold = int(rb.get("spawn_stand_hold_steps", 90))
            if n_hold > 0:
                self._spawn_stand_hold(n_hold)
                steps.append(f"spawn_stand_hold:{n_hold}")
        else:
            n_stab = int(rb.get("stabilize_steps", 0))
            if n_stab > 0:
                xy = (float(self._robot_start[0]), float(self._robot_start[1]))
                self._stabilize_robot(xy, n_stab)
                steps.append(f"stabilize:{n_stab}")

        if not spawn_standing and rb.get("micro_navigate_on_start", False):
            off = rb.get("micro_navigate_offset_xy", [0.1, 0.0])
            if isinstance(off, (list, tuple)) and len(off) >= 2:
                gx = float(self._robot_start[0]) + float(off[0])
                gy = float(self._robot_start[1]) + float(off[1])
                steps.append(
                    f"micro_navigate:{self._navigate_xy([gx, gy], max_steps=int(rb.get('micro_navigate_max_steps', 500)), threshold=float(rb.get('micro_navigate_threshold', self._navigation_threshold)))}"
                )
        return ",".join(steps)

    def _collision_patch_merom_scene(self) -> None:
        from pxr import PhysxSchema, Usd, UsdPhysics

        stage = self._api._env.runner._world.stage
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

    def _spawn_stand_hold(self, hold_steps: int) -> None:
        """Hold spawn XY with locomotion controller active so the dog stands immediately."""
        if self._env is None:
            return
        action_name = self._resolve_nav_action_name()
        xy = (float(self._robot_start[0]), float(self._robot_start[1]))
        hold_action = {action_name: [(xy[0], xy[1], 0.0)]}
        self._trace(
            f"spawn_stand_hold: {hold_steps} steps at ({xy[0]:.3f},{xy[1]:.3f}) "
            f"action={action_name!r}"
        )
        for _ in range(max(1, hold_steps)):
            with self._env_lock:
                self._last_obs, _, terminated, _, _ = self._env.step(action=hold_action)
            ep = terminated[0] if isinstance(terminated, (list, tuple)) else bool(terminated)
            if ep:
                break

    def _stabilize_robot(self, target_xy: tuple[float, float], settle_steps: int) -> None:
        action_name = self._resolve_nav_action_name()
        idle_action = {action_name: [(float(target_xy[0]), float(target_xy[1]), 0.0)]}
        for _ in range(settle_steps):
            with self._env_lock:
                self._last_obs, _, terminated, _, _ = self._env.step(action=idle_action)
            ep = terminated[0] if isinstance(terminated, (list, tuple)) else bool(terminated)
            if ep:
                break

    def _idle_step_if_due(self) -> None:
        if not self._idle_step_enabled or self._api is None or self._env is None:
            return
        now = time.monotonic()
        if now - self._last_idle_step_ts < self._idle_step_interval_s:
            return
        self._last_idle_step_ts = now
        action_name = self._resolve_nav_action_name()
        robot_obs = self._extract_robot_obs(self._last_obs)
        hold_xy = self._xy_from_robot_position(robot_obs.get("position") if robot_obs else None)
        if hold_xy is None:
            hold_xy = (float(self._robot_start[0]), float(self._robot_start[1]))
        hold_action = {action_name: [(float(hold_xy[0]), float(hold_xy[1]), 0.0)]}
        for _ in range(max(1, self._idle_steps_per_cycle)):
            with self._env_lock:
                self._last_obs, _, _, _, _ = self._env.step(action=hold_action)

    def _navigate_xy(
        self,
        xy: list[float],
        *,
        max_steps: int,
        threshold: float,
        action_name_override: str | None = None,
        arm_target: list[float] | None = None,
        arm_action_name: str = "arm_joint_controller",
    ) -> str:
        if self._env is None:
            return "Error: env not started"
        action_name = str(action_name_override or self._resolve_nav_action_name())
        robot_obs = self._extract_robot_obs(self._last_obs)
        start_xy = self._xy_from_robot_position(robot_obs.get("position") if robot_obs else None)
        if start_xy is None:
            start_xy = (float(self._robot_start[0]), float(self._robot_start[1]))
        warmup = max(0, int(self._navigation_warmup_steps))
        if warmup > 0:
            self._trace(
                f"navigate warmup: {warmup} hold steps at ({start_xy[0]:.3f},{start_xy[1]:.3f}) "
                f"action={action_name!r}"
            )
            self._stabilize_robot(start_xy, warmup)
        start_dist = math.hypot(start_xy[0] - float(xy[0]), start_xy[1] - float(xy[1]))
        self._trace(
            f"navigate start: from=({start_xy[0]:.3f},{start_xy[1]:.3f}) "
            f"goal=({float(xy[0]):.3f},{float(xy[1]):.3f}) dist={start_dist:.4f} "
            f"max_steps={max_steps} threshold={threshold}"
        )
        goal_action: dict[str, Any] = {action_name: [(float(xy[0]), float(xy[1]), 0.0)]}
        if arm_target is not None:
            goal_action[arm_action_name] = [list(arm_target)]
        dist = start_dist
        stable_finished = 0
        pos_xy: tuple[float, float] | None = start_xy
        log_every = self._navigation_log_interval
        for step_i in range(max_steps):
            with self._env_lock:
                self._last_obs, _, terminated, _, _ = self._env.step(action=goal_action)
            episode_terminated = terminated[0] if isinstance(terminated, (list, tuple)) else bool(terminated)
            if episode_terminated:
                self._trace(f"navigate terminated early at sim_step={step_i}")
                return "navigate terminated early"
            robot_obs = self._extract_robot_obs(self._last_obs)
            if robot_obs:
                pos_xy = self._xy_from_robot_position(robot_obs.get("position"))
                if pos_xy is not None:
                    dist = math.hypot(pos_xy[0] - float(xy[0]), pos_xy[1] - float(xy[1]))
            at_goal = pos_xy is not None and dist <= threshold
            ctrl = (robot_obs.get("controllers") or {}).get(action_name) or {} if robot_obs else {}
            if at_goal and bool(ctrl.get("finished")):
                stable_finished += 1
            else:
                stable_finished = 0
            finished_need = max(
                1, int(getattr(self, "_navigation_finished_stable_steps", 15))
            )
            settle_steps = max(0, int(getattr(self, "_navigation_settle_steps", 60)))
            if at_goal and stable_finished >= finished_need:
                self._trace(
                    f"navigate at goal dist={dist:.4f}, settling {settle_steps} steps"
                )
                for settle_i in range(settle_steps):
                    with self._env_lock:
                        self._last_obs, _, terminated, _, _ = self._env.step(
                            action=goal_action
                        )
                    if terminated[0] if isinstance(terminated, (list, tuple)) else bool(
                        terminated
                    ):
                        return "navigate terminated during settle"
                self._trace(f"navigate ok at sim_step={step_i} dist={dist:.4f}")
                return f"navigate ok: dist={dist:.4f} settled={settle_steps}"
            if step_i == 0 or (step_i + 1) % log_every == 0:
                pstr = (
                    f"({pos_xy[0]:.3f},{pos_xy[1]:.3f})"
                    if pos_xy is not None
                    else "?"
                )
                self._trace(
                    f"navigate sim_step={step_i + 1}/{max_steps} dist={dist:.4f} pos={pstr} "
                    f"finished_streak={stable_finished}"
                )
        self._trace(f"navigate failed after {max_steps} sim steps dist={dist:.4f}")
        return f"navigate failed: dist={dist:.4f}"

    def _resolve_waypoint_key(self, key: str) -> str:
        k = key.strip()
        for canon in self._waypoints:
            if canon.lower() == k.lower():
                return canon
        alias = self._waypoint_aliases.get(k.lower())
        if alias:
            for canon in self._waypoints:
                if canon.lower() == alias.strip().lower():
                    return canon
        return k

    def _rebuild_scene_narration(self) -> None:
        if not self._visible_objects:
            self._scene_narration_cn = "No visible_objects configured."
            return
        parts: list[str] = []
        for vo in self._visible_objects:
            shape = vo.get("shape_cn", "object")
            col = vo.get("color_label_cn", "")
            parts.append(f"{col} {shape}".strip() if col else str(shape))
        self._scene_narration_cn = "I can see: " + "; ".join(parts) + "."

    @staticmethod
    def _build_api(
        *,
        scene_asset_path: str,
        robot_start: Any,
        arm_mass_scale: float,
        objects_spec: Any,
        api_kwargs: dict[str, Any],
        robot_usd_path: str = "",
    ):
        ensure_bundled_internutopia()
        api_kwargs.pop("pythonpath", None)
        bridge = importlib.import_module("internutopia.bridge")
        objects_mod = importlib.import_module("internutopia_extension.configs.objects")
        PiperGo2ManipulationAPI = bridge.PiperGo2ManipulationAPI
        create_pipergo2_robot_cfg = bridge.create_pipergo2_robot_cfg
        DynamicCubeCfg = objects_mod.DynamicCubeCfg
        VisualCubeCfg = objects_mod.VisualCubeCfg

        rs = tuple(float(x) for x in robot_start) if isinstance(robot_start, list) else tuple(robot_start)
        robot_cfg = create_pipergo2_robot_cfg(position=rs, arm_mass_scale=arm_mass_scale)
        if robot_usd_path:
            robot_cfg.usd_path = robot_usd_path
        objects = []
        if isinstance(objects_spec, list):
            for item in objects_spec:
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
                if kind == "visual_cube":
                    cfg["color"] = list(cfg["color"])
                    objects.append(VisualCubeCfg(**cfg))
                else:
                    objects.append(DynamicCubeCfg(**cfg))
        headless = api_kwargs.pop("headless", None)
        if headless is None:
            headless = not bool(api_kwargs.pop("force_gui", False))
        return PiperGo2ManipulationAPI(
            scene_asset_path=scene_asset_path,
            robot_cfg=robot_cfg,
            objects=objects,
            headless=headless,
            **api_kwargs,
        )

    def _resolve_approach_xy(self, pick_prim_path: str, offset: float) -> tuple[float, float] | None:
        for obj in self._objects_spec or []:
            if isinstance(obj, dict) and obj.get("prim_path") == pick_prim_path:
                pos = obj.get("position")
                if pos and len(pos) >= 2:
                    return (float(pos[0]) - float(offset), float(pos[1]))
        pos = (self._pick_target_raw or {}).get("position")
        if pos and len(pos) >= 2:
            return (float(pos[0]) - float(offset), float(pos[1]))
        return None

    def _ensure_vla_cameras(self, cfg: dict[str, Any], hold_xy: tuple[float, float]) -> str | None:
        if self._vla_session is not None and self._vla_session.get("cameras"):
            return None
        if self._api is None or self._env is None:
            return "Error: API not started"
        from rollout.simulation import vla_pick as _vla
        import numpy as _np

        robot_prim_path = str(cfg.get("robot_prim_path", "/World/env_0/robots/pipergo2"))
        mounts = dict(cfg.get("cameras") or {})
        if not mounts:
            return "Error: vla.cameras not configured"
        action_name = self._resolve_nav_action_name()
        warmup_hold_action = {action_name: [(float(hold_xy[0]), float(hold_xy[1]), 0.0)]}
        robot_view, joint_indices = _vla.build_articulation_view(robot_prim_path)
        if robot_view is None:
            return "Error: ArticulationView init failed"
        stage = getattr(getattr(self._env, "runner", None), "_world", None)
        stage = getattr(stage, "stage", None) if stage else None
        if stage is None:
            try:
                import omni

                stage = omni.usd.get_context().get_stage()
            except Exception:
                return "Error: USD stage unavailable"
        cameras, flip_set = _vla.attach_cameras(
            stage=stage,
            env=self._env,
            env_lock=self._env_lock,
            hold_action=warmup_hold_action,
            mounts=mounts,
            resolution=tuple(cfg.get("cam_resolution", [640, 400])),
            warmup_steps=int(cfg.get("cam_warmup_steps", 60)),
        )
        if not cameras:
            return "Error: no VLA cameras attached"
        sim_hz = int(cfg.get("sim_hz", 240))
        control_hz = int(cfg.get("control_hz", 10))
        self._vla_session = {
            "controller": None,
            "robot_view": robot_view,
            "joint_indices": joint_indices,
            "cameras": cameras,
            "flip_set": flip_set,
            "stage": stage,
            "sim_steps_per_action": max(1, sim_hz // max(1, control_hz)),
            "arm_action_name": str(cfg.get("arm_action_name", "arm_joint_controller")),
            "live_hold": {"action": dict(warmup_hold_action)},
            "_np": _np,
        }
        return None

    def _ensure_vla_controller(self, cfg: dict[str, Any]) -> str | None:
        session = self._vla_session
        if session is None or not session.get("cameras"):
            return "Error: VLA cameras not initialized"
        if session.get("controller") is not None:
            return None
        from rollout.simulation import vla_pick as _vla

        ckpt_path = str(cfg.get("ckpt_path", "")).strip()
        if not ckpt_path or not Path(ckpt_path).exists():
            return f"Error: vla ckpt not found: {ckpt_path!r}"
        robot_view = session["robot_view"]
        joint_indices = session["joint_indices"]
        cameras = session["cameras"]
        flip_set = session["flip_set"]
        live_hold = session["live_hold"]
        _np = session["_np"]
        training_max = float(cfg.get("vla_gripper_training_max", 0.28))
        piper_max = float(cfg.get("piper_gripper_width_max", 0.07))

        def _read_images():
            out: dict[str, Any] = {}
            for name, cam in cameras.items():
                rgb = _vla.grab_rgb(cam, self._env, self._env_lock, live_hold["action"])
                if rgb is None or not rgb.any():
                    return None
                if name in flip_set:
                    rgb = _np.ascontiguousarray(_np.fliplr(rgb))
                out[name] = rgb
            return out

        session["controller"] = _vla.VLAController(
            ckpt_path=ckpt_path,
            task_text=str(cfg.get("task_text", "pick up the red cube")),
            gripper_scale=float(cfg.get("gripper_scale", piper_max / training_max)),
            gripper_bias=float(cfg.get("gripper_bias", 0.0)),
            state_gripper_scale=float(cfg.get("state_gripper_scale", training_max / piper_max)),
            joint_limits=cfg.get("joint_limits") or _vla.DEFAULT_PIPER_JOINT_LIMITS,
            max_delta_arm=float(cfg.get("max_per_tick_delta_arm", 0.45)),
            max_delta_gripper=float(cfg.get("max_per_tick_delta_gripper", 0.06)),
            read_state7=lambda: _vla.read_piper_state7(robot_view, joint_indices),
            read_images=_read_images,
        )
        session["controller"].set_n_action_steps(int(cfg.get("n_action_steps", 2)))
        return None

    def _collect_vla_images(self) -> dict[str, Any] | None:
        session = self._vla_session
        if not session or not session.get("cameras"):
            return None
        from rollout.simulation import vla_pick as _vla

        live_hold = session.get("live_hold", {}).get("action", {})
        _np = session["_np"]
        out: dict[str, Any] = {}
        for name, cam in session["cameras"].items():
            rgb = _vla.grab_rgb(cam, self._env, self._env_lock, live_hold)
            if rgb is None:
                continue
            if name in session.get("flip_set", set()):
                rgb = _np.ascontiguousarray(_np.fliplr(rgb))
            out[name] = rgb
        return out or None

    def _read_vla_state7(self):
        session = self._vla_session
        if not session or not session.get("robot_view"):
            return None
        from rollout.simulation import vla_pick as _vla

        return _vla.read_piper_state7(session["robot_view"], session["joint_indices"])

    @staticmethod
    def _normalize_color_hint(raw: Any) -> str:
        hint = str(raw or "").strip().lower()
        alias_map = {"红": "red", "红色": "red", "蓝": "blue", "绿": "green", "黄": "yellow"}
        return alias_map.get(hint, hint)

    @staticmethod
    def _result_ok(result: Any) -> bool:
        if hasattr(result, "success"):
            return bool(result.success)
        if isinstance(result, dict):
            return bool(result.get("success", False))
        return result is not None

    @staticmethod
    def _result_steps(result: Any) -> Any:
        if hasattr(result, "steps"):
            return result.steps
        if isinstance(result, dict):
            return result.get("steps", "?")
        return "?"

    @staticmethod
    def _tupleize_grasp_dict(raw: dict[str, Any]) -> dict[str, Any]:
        if not raw:
            return {}
        out: dict[str, Any] = {}
        for k, v in raw.items():
            if k in ("position", "pre_position", "post_position", "orientation") and isinstance(v, list):
                out[k] = tuple(float(x) for x in v)
            elif k == "metadata" and isinstance(v, dict):
                out[k] = dict(v)
            else:
                out[k] = v
        return out

    @staticmethod
    def _extract_robot_obs(obs_data: Any) -> dict[str, Any] | None:
        if isinstance(obs_data, dict) and "position" in obs_data:
            return obs_data
        if isinstance(obs_data, dict):
            for key in ("pipergo2", "pipergo2_0"):
                if key in obs_data:
                    return obs_data[key]
        if isinstance(obs_data, (list, tuple)) and obs_data:
            first = obs_data[0]
            if isinstance(first, dict):
                for key in ("pipergo2", "pipergo2_0"):
                    if key in first:
                        return first[key]
                return first
        return None

    @staticmethod
    def _xy_from_robot_position(position: Any) -> tuple[float, float] | None:
        if position is None:
            return None
        try:
            if hasattr(position, "tolist"):
                position = position.tolist()
            if isinstance(position, (list, tuple)) and len(position) >= 2:
                return (float(position[0]), float(position[1]))
        except (TypeError, ValueError):
            return None
        return None

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

    @staticmethod
    def _safe_json(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except TypeError:
            return str(value)
