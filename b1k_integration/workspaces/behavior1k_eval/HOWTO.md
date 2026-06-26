# BEHAVIOR-1K 评测平台

PhyAgentOS benchmark 层：**选任务列表 → 选策略 → 一键评测**。  
默认走 **TargetWS + Runtime Watchdog**（与 LIBERO 相同架构）。

## 前置

| 角色 | 环境 |
|------|------|
| `run_benchmark.py` / `run_runtime_watchdog.py` | **paos** |
| B1K TargetWS server | **behavior** conda + Isaac Sim |
| BEHAVIOR-1K 源码 | `/home/zyserver/work/BEHAVIOR-1K` |

不要在 paos 里 `source isaacsim/setup_python_env.sh`。

## 推荐：TargetWS 双终端

**终端 A** — 启动仿真 TargetWS（带 GUI）：

```bash
export DISPLAY=:1
bash b1k_integration/scripts/start_behavior1k_server.sh --gui --port 9004
```

**终端 B** — 跑 watchdog 或 benchmark：

```bash
conda activate paos
cd ~/work/my_project/new/PhyAgentOS

# 单 session 冒烟
python scripts/run_runtime_watchdog.py \
  --workspace b1k_integration/workspaces/behavior1k_eval \
  --session-id sess_b1k_turning_on_radio_0_smoke \
  --once

# benchmark 编排（默认 runtime_watchdog）
python b1k_integration/scripts/run_benchmark.py \
  --benchmark behavior-1k \
  --suite smoke3 \
  --policy dummy_baseline \
  --tasks turning_on_radio \
  --instance-ids 0
```

无窗口批量：终端 A 去掉 `--gui`（或 server 加 `--headless`）。

## 查看注册表

```bash
python b1k_integration/scripts/run_benchmark.py --list-benchmarks
python b1k_integration/scripts/run_benchmark.py --list-policies
python b1k_integration/scripts/run_benchmark.py --list-tasks --suite smoke3
```

## 策略

| policy id | 状态 | Watchdog 路径 |
|-----------|------|----------------|
| `dummy_baseline` | available | `dummy://local` + `b1k_dummy_policy_adapter`（轻微摆动） |
| `b1k_websocket` | available | 需外部 WebSocket policy server |
| `openpi_r1pro` | reserved | 下载权重后注册 `openpi://` endpoint |

## 配置文件

| 文件 | 作用 |
|------|------|
| `BENCHMARKS.md` | benchmark / suite；`execution_backend: runtime_watchdog` |
| `POLICIES.md` | 策略 endpoint |
| `TARGETS.md` | `behavior1k_r1pro_sim` → `targetws://127.0.0.1:9004` |
| `SKILLRUNTIME.md` | `behavior1k_vla` |
| `SESSIONS.md` | benchmark 生成的评测队列 |

## Legacy：原生 eval.py 子进程

在 `BENCHMARKS.md` 将 `execution_backend` 改回 `behavior1k_native` 即可恢复旧路径（Hydra + `eval.py`）。

## 相关文档

- TargetWS 细节：`PhyAgentOS/runtime/targets/remote/behavior1k/README.md`
- **OpenPI 三终端测评（对齐 LIBERO）**：`OPENPI_E2E.md`
