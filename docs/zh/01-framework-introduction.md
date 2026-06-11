# PhyAgentOS-G 框架介绍

> 面向所有人的项目概述：游戏智能体研究理念、技术架构、当前进展、路线图。

---

## 目录

- [1.1 项目概述](#11-项目概述)
- [1.2 设计理念](#12-设计理念)
- [1.3 技术架构](#13-技术架构)
- [1.4 核心特性](#14-核心特性)
- [1.5 当前进展](#15-当前进展)
- [1.6 路线图与 TODO](#16-路线图与-todo)
- [1.7 已验证通路](#17-已验证通路)
- [1.8 项目结构](#18-项目结构)

---

## 1.1 项目概述

**PhyAgentOS-G** 是 [PhyAgentOS](https://github.com/PhyAgentOS/PhyAgentOS) 的 Game Agent 分支，基于主分支 **v0.1.4** 重构而来，专注**通用游戏智能体**研究。移除了通用 HAL 硬件驱动层，保留了 Session-Centered Runtime 核心架构，版本号从 v0.0.x 起始以独立追踪 Game Agent 分支的演进。由**中山大学 HCP 实验室**与**鹏城实验室**联合开发，基于 [nanobot](https://github.com/HKUDS/nanobot) 构建。

### 核心价值

将具身智能体的学习和验证迁移到游戏环境，以极低成本探索智能行为的核心能力，并将已验证的策略迁移到仿真与真机环境：

- **低成本验证智能行为**：游戏提供复杂交互、长期记忆依赖和开放世界，无需硬件成本即可迭代 Agent 能力
- **同一套协议，三种环境**：Session 协议在 Game / Simulation / Real Robot 间无差别运行
- **全程可审计**：状态、动作、感知结果以 Markdown + YAML 落盘，每一步可追溯复现
- **三段解耦**：RolloutTarget + SkillRuntime + TargetAdapter 分离，新增目标 ~100 行代码

### 当前三大支柱

| 支柱 | 代表 | 状态 | 说明 |
|------|------|------|------|
| 🎮 **Game** | Minecraft | ✅ 已就绪 | 全链路打通：Windows bridge → ngrok → Linux Agent |
| 🧪 **Simulation** | LIBERO + pi0.5 | ✅ 已验证 | Benchmark 评测 + policy 闭环 |
| 🤖 **Real Robot** | 真机验证 | 🔶 规划中 | 策略迁移验证 |

### 关键数据

| 指标 | 数值 |
|------|------|
| 框架版本 | v0.0.3（基于 PhyAgentOS v0.1.4 重构） |
| Python 要求 | ≥ 3.11 |
| License | MIT |
| Runtime 代码规模 | ~7200 行 (95 个 Python 文件) |
| 已验证 Target | Minecraft、DummySim、LIBERO |
| 已验证 SkillRuntime | OpenPI (pi05)、MinecraftSkill、BuiltinSkill |

### 关联资源

- **GitHub**: [https://github.com/PhyAgentOS/PhyAgentOS](https://github.com/PhyAgentOS/PhyAgentOS)
- **PhyAgentOS 母项目**: [https://github.com/PhyAgentOS/PhyAgentOS](https://github.com/PhyAgentOS/PhyAgentOS)（main 分支为旧架构 HAL）

---

## 1.2 设计理念

### 1.2.1 万物皆 Markdown（State-as-a-File）

PhyAgentOS-G 将一切运行时状态以 Markdown 文件形式暴露在工作区中。Track A（Agent 大脑）和 Track B（Runtime 执行平面）之间不通过 Python 函数调用通信，而是通过读写共享文件交换信息：

```
Track A (Agent)          工作区文件           Track B (Runtime)
    │                                            │
    ├── 读取 ENVIRONMENT.md ─────────────→ 写回状态
    │                                            │
    ├── 写入 SESSIONS.md ─────────────────→ 消费执行
    │                                            │
    ├── 读取 LESSONS.md ←────────────────── 回写经验
```

这带来三个关键收益：**彻底解耦**（Agent 和 Runtime 可独立进程/机器）、**极度透明**（随时查看 Markdown 文件了解系统状态）、**天然可审计**（历史状态以文件形式保存）。

### 1.2.2 认知-物理解耦（Dual-Track）

| 轨道 | 职责 | 入口 |
|------|------|------|
| **Track A（认知层）** | 理解用户意图、规划动作、Critic 校验、管理记忆 | `paos agent` |
| **Track B（执行层）** | Session 级执行监督、Target/Policy 调用、状态与 artifact 写回 | 随 `paos agent` 自动启动 |

两轨道通过文件协议边界严格隔离。Track A 不知道 Target 是游戏还是仿真，Track B 不知道 LLM Prompt。

### 1.2.3 Session-Centered Runtime

Runtime 以执行会话（Session）为核心：

- Agent 将任务封装为 Session 写入 `SESSIONS.md`
- WatchdogSupervisor 读取、校验（Preflight）、分派、执行 Session
- 执行结果回写到 `SESSIONS.md`、`ENVIRONMENT.md`、`LESSONS.md`

同一套 Session 协议在 game / debug / simulation / real_robot 四类 Target 上无差别运行。

### 1.2.4 三阶段验证闭环

```
Game Agent (低成本迭代)
    → 验证长期决策、空间推理、任务规划能力
    → Simulation (Benchmark 评测 + 批量经验挖掘)
    → Real Robot (真机迁移验证)
```

---

## 1.3 技术架构

### 1.3.1 整体架构

```
                    ┌─────────────────────────────┐
                    │     认知层（Track A）         │
                    │  Planner / Critic / Memory   │
                    │     → 写 SESSIONS.md         │
                    └──────────────┬──────────────┘
                                   │ 文件协议边界
                    ┌──────────────┴──────────────┐
                    │     Base Runtime            │
                    │  WatchdogSupervisor          │
                    │  SessionRegistry             │
                    │  LESSONS.md 经验库           │
                    └──────┬──────┬──────┬────────┘
                           │      │      │
              ┌────────────┼──────┼──────┼────────────┐
              ▼            ▼      ▼      ▼            ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │ Game Target  │ │ Sim Target   │ │ Real Target  │
    │ Minecraft    │ │ LIBERO       │ │ 真机验证     │
    └──────────────┘ └──────────────┘ └──────────────┘
```

### 1.3.2 Runtime 执行链路

```
WatchdogSupervisor
  → SessionScheduler（读取 SESSIONS.md，claim pending session）
    → RuntimeCompatibilityPreflight（strick 前置校验）
      → SessionRunner（绑定 Target + SkillRuntime）
        → SkillRuntime（执行策略循环：observe → predict → action → step）
          → TargetSessionHandle（驱动 Target.action_chunk()）
            → 写回 SESSIONS.md / ENVIRONMENT.md / LESSONS.md / artifacts
```

### 1.3.3 三段解耦：Adapter + Bridge

```
Agent 产生意图 → SESSIONS.md
  → TargetAdapter（原始观测 → Runtime 统一观测格式）
    → PolicyAdapter（Runtime 观测 → Policy 输入格式）
      → ActionBridge（Policy 输出 → Target 可执行动作）
```

`AdapterPlan` 自动编排适配步骤，消灭 target × skill 的组合爆炸。

### 1.3.4 核心接口：BaseRolloutTarget

三个场景的唯一切入点：

```python
class BaseRolloutTarget(ABC):
    def build(self) -> None:          # 初始化目标资源
    def describe(self) -> dict:       # 返回能力声明
    def reset(self, session_ctx) -> dict:  # 重置→返回初始观测
    def observe(self) -> dict:        # 获取当前观测
    def action_chunk(self, action_chunk) -> dict:  # 执行动作块
    def execution_status(self) -> dict:  # 返回执行状态
    def cancel(self, reason) -> None:    # 中断执行
    def close(self) -> None:          # 释放资源
```

WatchdogSupervisor 不需要知道 Target 是游戏、仿真还是真机。

### 1.3.5 解耦边界

| 组件 | 可以知道 | 绝不能知道 |
|------|---------|-----------|
| **RolloutTarget** | 自己怎么 build/reset/step | Policy 推理、Skill 逻辑、上层 Agent |
| **SkillRuntime** | 怎么调用 target 和 policy_client | Target 内部实现 |
| **TargetAdapter** | 怎么做数据变换 | Policy 推理、Target 内部状态 |
| **WatchdogSupervisor** | 怎么管理状态机、路由 | 具体怎么执行 step |

---

## 1.4 核心特性

| 特性 | 说明 |
|------|------|
| **Session-Centered Runtime** | WatchdogSupervisor → SessionRunner → SkillRuntime → TargetSessionHandle |
| **Target-Configured** | game / debug / simulation / real_robot 四类 Target，TARGETS.md 统一注册 |
| **Adapter + Bridge** | TargetAdapter + PolicyAdapter + ActionBridge 三段解耦，AdapterPlan 自动编排 |
| **双轨 Skill Runtime** | PolicySkillRuntime 维护策略闭环 + BuiltinSkillRuntime 管理 Agent 交互闭环 |
| **Strict Preflight** | 6 项前置校验（target / sensor / perception / adapter / action / tool），不合格拒绝 |
| **文件协议矩阵** | TARGETS.md · SKILLRUNTIME.md · SESSIONS.md · ENVIRONMENT.md · LESSONS.md |
| **感知插件体系** | SensorConfig / PerceptionConfig YAML + EnvironmentWriter 可审计写回 |
| **Game Agent CLI** | `paos minecraft` 命令行直接控制游戏 bot |

---

## 1.5 当前进展

### 版本历程

| 版本 | 日期 | 里程碑 |
|:-----|:-----|:-------|
| v0.1.4 | 2026-06-05 | 母版本：优化启动流程；通信协议规范；Game Agent & Benchmarking 就绪 |
| v0.0.1 | 2026-05-29 | Minecraft 全链路就绪：云端 Agent 连接用户本地服务器 |
| v0.0.2 | 2026-05-29 | Minecraft 通路优化：终端 + 游戏内聊天双通道控制 |
| v0.0.3 | 2026-06-11 | 项目定位重构：从通用 HAL 架构迁移为 Game Agent 研究框架（PhyAgentOS-G） |

> PhyAgentOS-G 基于主分支 v0.1.4 重构，版本号从 0.0.x 起始。

### 已达成能力

| 能力 | 说明 |
|------|------|
| **Minecraft Game Agent** | 全链路打通：Windows mineflayer bridge → ngrok → Linux Agent。无 pyCraft 依赖，纯 HTTP 通信 |
| **Session-Centered Runtime** | WatchdogSupervisor 完整状态机（pending → claimed → running → succeeded/failed） |
| **Strict Preflight** | 6 项校验（target / sensor / perception / adapter contract / action contract / tool） |
| **LIBERO Benchmark** | TargetWS server + proxy + adapter，WebSocket + MsgPack 通信 |
| **pi0.5 Policy 闭环** | LeRobot pi0 server + OpenPI client + skill runtime，支持 action chunk |
| **感知管道** | PerceptionRuntime + 5 个感知插件（dummy/sam3/yolo/rgbd/sim_oracle）+ EnvironmentWriter |
| **E2E 验收脚本** | run_pi05_libero_real_e2e.py（172行），通过 WatchdogSupervisor 端到端执行 |

---

## 1.6 路线图与 TODO

### 短期重点（1-2 月）

**Game Agent 扩展**：
- [ ] 星露谷（Stardew Valley）Game Target 实现（SMAPI mod + HTTP bridge）
- [ ] 跨 season/跨日长期记忆验证
- [ ] NPC 关系网络与社交记忆
- [ ] 14 天无人干预运行验收
- [ ] Minecraft 多任务并行执行

**Runtime 增强**：
- [ ] Simulation Target 实现（MuJoCo / ManiSkill / RoboCasa）
- [ ] Real Robot 验证 Target（Franka / Go2）
- [ ] Session 状态机健全：pending → claimed → running → succeeded / failed / timed_out
- [ ] Fallback chain 机制（执行失败自动降级策略）

**Perception 深化**：
- [ ] 相机/LiDAR 接入标准化
- [ ] 场景图构建与写回协议完善

### 中期方向（3-6 月）

- **游戏→仿真经验迁移**：LESSONS.md 从游戏积累的经验自动应用于仿真
- **批量 Benchmark 评测**：BenchmarkHarness 自动化评测框架
- **Policy Server 标准化**：统一的 WebSocket + msgpack 通信协议
- **真机策略迁移验证**：仿真训练的策略在真机上验证

---

## 1.7 已验证通路

### Minecraft Game Agent 全链路

```
[Windows 11]
  Minecraft Java Edition (1.20.4)
       ↑ localhost:25565
  mineflayer bridge (Node.js)           ← 机器人引擎
       ↑ localhost:3001 (HTTP API)
  ngrok tunnel                          ← 公网暴露
       ↓ HTTPS

[Linux 云端 — PhyAgentOS-G]
  MinecraftTarget                       ← HTTP 客户端
       ↑
  MinecraftSkillRuntime                 ← episode 驱动循环
       ↑
  WatchdogSupervisor                    ← session 监督器
       ↑
  Agent (Planner/Critic)               ← 通过 SESSIONS.md 下发任务
```

**启动示例**：

Windows 端：
```powershell
cd mc_bridge
$env:MC_HOST="localhost"; $env:MC_PORT="25565"; $env:BOT_NAME="paos"
$env:MC_VERSION="1.20.4"; $env:API_PORT="3001"
node bridge_server.js
ngrok http 3001 --region=ap
```

Linux 端：
```bash
# 配置 TARGETS.md 和 SKILLRUNTIME.md 后
paos minecraft say "挖5个橡木然后过来"
```

完整部署文档：见 [Minecraft 场景文档](../scenarios/game/minecraft/zh/deployment.md)

### LIBERO Benchmark + pi0.5 闭环

```bash
# TargetWS 机器
MUJOCO_GL=egl PYTHONWARNINGS=ignore \
python PhyAgentOS/runtime/targets/remote/libero/server.py --host 0.0.0.0 --port 9002

# Policy 机器
python -m PhyAgentOS.runtime.policy.openpi.lerobot_pi0_server \
  --model-dir /path/to/pi05/checkpoint --host 0.0.0.0 --port 8000

# Agent 侧
paos agent -m "运行已配置的 LIBERO benchmark 任务"
```

E2E 验证脚本：`scripts/run_pi05_libero_real_e2e.py`

### DummySimTarget 快速冒烟

```bash
paos onboard
paos agent -m "使用 dummy_sim target 运行一次冒烟测试"
```

---

## 1.8 项目结构

```
PhyAgentOS-G/
│
├── PhyAgentOS/agent/          # Track A — Agent 大脑
│   ├── loop.py                #   主 Agent 循环
│   ├── context.py             #   上下文窗口构建
│   ├── memory.py              #   记忆系统
│   ├── skills.py              #   Skill 加载与执行
│   └── tools/                 #   内置工具（文件、Shell、Web 等）
│
├── PhyAgentOS/runtime/        # Track B — 执行平面
│   ├── watchdog/              #   WatchdogSupervisor · scheduler · registry
│   ├── sessions/              #   SessionRunner · TargetSessionHandle
│   ├── targets/               #   RolloutTarget 实现
│   │   ├── game/              #   Minecraft target
│   │   ├── local/             #   DummySimTarget
│   │   └── remote/libero/     #   LIBERO TargetWS server + proxy
│   ├── skillruntime/          #   PolicySkillRuntime · BuiltinSkillRuntime
│   │   ├── policy/            #   OpenPI policy runtime
│   │   └── game/              #   Minecraft skill runtime
│   ├── adapters/              #   TargetAdapter · PolicyAdapter · ActionBridge
│   │   ├── libero/            #   LIBERO target adapter
│   │   ├── openpi/            #   OpenPI policy adapters (pi05/dummy)
│   │   └── minecraft/         #   Minecraft adapter
│   ├── policy/openpi/         #   OpenPI client + LeRobot pi0 server
│   ├── perception/            #   感知运行时 · EnvironmentWriter · 插件管道
│   ├── preflight/             #   RuntimeCompatibilityPreflight
│   ├── schemas/               #   Pydantic Session/Contract Schema
│   ├── workspace/             #   Runtime workspace 生命周期管理
│   └── communication/         #   MsgPack · WebSocket 通信
│
├── PhyAgentOS/cli/            # CLI 入口（paos agent / onboard / minecraft）
├── PhyAgentOS/skills/         # Agent 内置 Skills（benchmarking 等）
├── PhyAgentOS/config/         # Pydantic 配置模型
├── PhyAgentOS/templates/      # 工作区模板文件（TARGETS.md 等）
├── scripts/                   # E2E 验收脚本 · workspace 初始化
├── bridge/                    # TypeScript 桥接层
├── docs/                      # 文档（中英文）
│   ├── zh/                    #   中文文档（框架介绍 · 用户手册 · 开发者手册）
│   ├── en/                    #   英文文档
│   └── scenarios/game/        #   游戏场景文档（Minecraft 部署与使用）
└── pyproject.toml             # Python 包配置
```

---

## 后续阅读

- [Part 2: 用户手册](02-user-manual.md) — 快速开始、Minecraft 配置、仿真验证、排障
- [Part 3: 开发者手册](03-developer-manual.md) — API 接口、Target/Adapter/Skill 开发、代码风格

> **下一步**：如果只想把系统跑起来，直接进入 [用户手册](02-user-manual.md)。
