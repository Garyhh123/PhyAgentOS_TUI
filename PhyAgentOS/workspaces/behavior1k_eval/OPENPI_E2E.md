# BEHAVIOR-1K OpenPI 三终端测评（对齐 LIBERO + π0.5）

## 架构

```
终端 A  behavior1k/server.py     →  targetws://127.0.0.1:9004
终端 B  serve_b1k.py (pi0_b1k)  →  b1k-ws://127.0.0.1:8000
终端 C  run_b1k_openpi_real_e2e →  Watchdog 闭环
```

与 LIBERO 的区别：**B1K 不能用 `lerobot_pi0_server`**，需用官方 baseline 的 `serve_b1k.py`（OmniGibson WebSocket 协议 + `B1KPolicyWrapper`）。

## 前置

| 项 | 说明 |
|----|------|
| BEHAVIOR-1K | `/home/zyserver/work/BEHAVIOR-1K` |
| b1k-baselines | `git clone --recurse-submodules https://github.com/StanfordVL/b1k-baselines.git` |
| openpi venv | **一次性**：`cd openpi && GIT_LFS_SKIP_SMUDGE=1 uv sync`（**不要**装 OmniGibson） |
| pi0_b1k 权重 | 微调或下载官方 checkpoint（见下方链接） |
| conda | A=`behavior`，B=openpi `uv` 环境，C=`paos` |

### 环境（终端 B）

只需 b1k-baselines 的 **openpi uv venv**（`uv sync`），**不需要**把 OmniGibson 装进 openpi 环境（避免 numba/coverage 冲突）。

```bash
cd ~/work/b1k-baselines/baselines/openpi && GIT_LFS_SKIP_SMUDGE=1 uv sync   # 首次
```

### Demo 权重（turning_on_radio）

官方 50k step checkpoint：[Google Drive](https://drive.google.com/file/d/1YU7evHBj7vfjmE-tNK-Rbie8ytholQTc/view)  
解压后 `CHECKPOINT_DIR` 指向含 `params/` 或 orbax 权重的**那一层目录**（与 `serve_b1k.py --policy.dir=` 一致）。

## 三终端命令

**终端 A — B1K 仿真 TargetWS（GUI）**

```bash
export DISPLAY=:1
bash scripts/start_behavior1k_server.sh --gui --port 9004
```

**终端 B — pi0 B1K policy server**

```bash
# 示例：turning_on_radio 官方 demo checkpoint 路径（按你本机实际路径修改）
export CHECKPOINT_DIR=/path/to/pi0_b1k/turning_on_radio/checkpoint
export TASK_NAME=turning_on_radio
bash scripts/start_b1k_openpi_policy_server.sh
```

**终端 C — 跑一条 e2e session**

```bash
conda activate paos
cd ~/work/my_project/new/PhyAgentOS

python scripts/run_b1k_openpi_real_e2e.py \
  --policy-endpoint b1k-ws://127.0.0.1:8000 \
  --target-endpoint targetws://127.0.0.1:9004 \
  --task-name turning_on_radio \
  --instance-id 0 \
  --max-steps 200
```

或用已有 workspace + watchdog：

```bash
python scripts/run_runtime_watchdog.py \
  --workspace /tmp/phyagentos_b1k_openpi_e2e \
  --session-id b1k_turning_on_radio_i0 \
  --once
```

（先跑一遍 `run_b1k_openpi_real_e2e.py` 生成 workspace。）

## 权重从哪来

1. **官方 baseline 微调**（推荐）  
   按 [BEHAVIOR baselines](https://behavior.stanford.edu/challenge/baselines.html) 在 `b1k-baselines/baselines/openpi` 里：
   - `uv run scripts/compute_norm_stats.py --config-name pi0_b1k`
   - `uv run scripts/train_val.py pi0_b1k ...`
   - 官方提供 `turning_on_radio` 等任务的 50k step demo checkpoint 链接

2. **不能复用 LIBERO 的 `pi05_libero`**  
   观测/动作空间完全不同（3 相机 + 256 proprio → 23 维 joint）。

## 配置文件对应关系

| LIBERO | B1K |
|--------|-----|
| `libero/server.py :9002` | `start_behavior1k_server.sh :9004` |
| `lerobot_pi0_server` + `openpi://` | `serve_b1k.py` + `b1k-ws://` |
| `openpi_pi05_adapter` | `b1k_openpi_policy_adapter` |
| `run_pi05_libero_real_e2e.py` | `run_b1k_openpi_real_e2e.py` |

## GPU 显存（终端 B 常见 OOM）

pi0_b1k 加载后约占 **18 GiB** 显存（24 GiB 卡上与 B1K 仿真同卡一般够用）。

若出现 `RESOURCE_EXHAUSTED: Out of memory`：

1. **上次 policy server 未正常退出**，Python 进程仍占 ~18 GiB：
   ```bash
   nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory --format=csv
   kill <pid>   # 通常是 openpi/.venv/bin/python
   ```
2. 确认空闲显存 ≥ 12 GiB 后再启动；启动脚本会自动做 preflight 检查。
3. 终端 A（OmniGibson）与 B 同卡时，先起 A 再起 B；不要用 Ctrl+Z 挂起 B。

## Dummy 冒烟（无需权重）

仍可用之前的 dummy 路径：

```bash
# 终端 A 同上
# 终端 C
python scripts/run_runtime_watchdog.py \
  --workspace PhyAgentOS/workspaces/behavior1k_eval \
  --session-id sess_b1k_turning_on_radio_0_smoke \
  --once
```
