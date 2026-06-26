"""Minimal omnigibson.eval_utils shim for openpi ``b1k_policy.py``.

openpi imports ``PROPRIOCEPTION_INDICES`` from omnigibson, which pulls numba and
breaks in the openpi uv venv (coverage conflict).  Policy serving only needs the
R1Pro slice table — install this shim before importing openpi.
"""

from __future__ import annotations

import sys
from collections import OrderedDict
from types import ModuleType

import numpy as np

# Copied from BEHAVIOR-1K OmniGibson omnigibson/learning/utils/eval_utils.py (R1Pro).
PROPRIOCEPTION_INDICES = {
    "R1Pro": OrderedDict(
        {
            "joint_qpos": np.s_[0:28],
            "joint_qpos_sin": np.s_[28:56],
            "joint_qpos_cos": np.s_[56:84],
            "joint_qvel": np.s_[84:112],
            "joint_qeffort": np.s_[112:140],
            "robot_pos": np.s_[140:143],
            "robot_ori_cos": np.s_[143:146],
            "robot_ori_sin": np.s_[146:149],
            "robot_2d_ori": np.s_[149:150],
            "robot_2d_ori_cos": np.s_[150:151],
            "robot_2d_ori_sin": np.s_[151:152],
            "robot_lin_vel": np.s_[152:155],
            "robot_ang_vel": np.s_[155:158],
            "arm_left_qpos": np.s_[158:165],
            "arm_left_qpos_sin": np.s_[165:172],
            "arm_left_qpos_cos": np.s_[172:179],
            "arm_left_qvel": np.s_[179:186],
            "eef_left_pos": np.s_[186:189],
            "eef_left_quat": np.s_[189:193],
            "gripper_left_qpos": np.s_[193:195],
            "gripper_left_qvel": np.s_[195:197],
            "arm_right_qpos": np.s_[197:204],
            "arm_right_qpos_sin": np.s_[204:211],
            "arm_right_qpos_cos": np.s_[211:218],
            "arm_right_qvel": np.s_[218:225],
            "eef_right_pos": np.s_[225:228],
            "eef_right_quat": np.s_[228:232],
            "gripper_right_qpos": np.s_[232:234],
            "gripper_right_qvel": np.s_[234:236],
            "trunk_qpos": np.s_[236:240],
            "trunk_qvel": np.s_[240:244],
            "base_qpos": np.s_[244:247],
            "base_qpos_sin": np.s_[247:250],
            "base_qpos_cos": np.s_[250:253],
            "base_qvel": np.s_[253:256],
        }
    ),
}


def install_omnigibson_eval_utils_shim() -> None:
    """Register stub ``omnigibson.learning.utils.eval_utils`` if not already present."""
    key = "omnigibson.learning.utils.eval_utils"
    if key in sys.modules:
        return

    eval_utils = ModuleType(key)
    eval_utils.PROPRIOCEPTION_INDICES = PROPRIOCEPTION_INDICES

    utils_mod = ModuleType("omnigibson.learning.utils")
    utils_mod.eval_utils = eval_utils

    learning_mod = ModuleType("omnigibson.learning")
    learning_mod.utils = utils_mod

    og_mod = ModuleType("omnigibson")
    og_mod.learning = learning_mod

    sys.modules["omnigibson"] = og_mod
    sys.modules["omnigibson.learning"] = learning_mod
    sys.modules["omnigibson.learning.utils"] = utils_mod
    sys.modules[key] = eval_utils
