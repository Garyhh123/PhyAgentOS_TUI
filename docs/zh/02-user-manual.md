# PhyAgentOS-G 用户手册

> 面向使用者的运行手册：安装部署、Game Agent 配置、仿真验证、排障指南。

---

## 目录

- [2.1 手册定位](#21-手册定位)
- [2.2 系统工作原理](#22-系统工作原理)
- [2.3 安装与环境准备](#23-安装与环境准备)
- [2.4 5 分钟快速开始](#24-5-分钟快速开始)
- [2.5 配置详解](#25-配置详解)
- [2.6 场景使用指南](#26-场景使用指南)
  - [2.6.1 DummySimTarget 冒烟测试](#261-dummysimtarget-冒烟测试)
  - [2.6.2 Minecraft Game Agent](#262-minecraft-game-agent)
  - [2.6.3 LIBERO Benchmark 仿真验证](#263-libero-benchmark-仿真验证)
- [2.7 运行时文件说明](#27-运行时文件说明)
- [2.8 常见交互示例](#28-常见交互示例)
- [2.9 常见问题排查](#29-常见问题排查)

---

## 2.1 手册定位

### 适合谁

- 希望快速跑通 PhyAgentOS-G 的首次使用者
- 需要部署 Minecraft Game Agent 的研究者
- 需要运行仿真 Benchmark 验证的研究者
- 需要理解运行时工作区文件如何变化的调试人员

### 不适合谁

如需进行二次开发、添加新 Game Target 或编写 Adapter，请阅读 [Part 3: 开发者手册](03-developer-manual.md)。

---

## 2.2 系统工作原理

### 2.2.1 双轨结构

PhyAgentOS-G 是一个显式解耦的双轨运行架构：

- **Track A（Agent / 大脑）**：负责理解用户输入、规划动作、调用工具、Critic 校验。通过 `paos agent` 启动。
- **Track B（Runtime / 执行层）**：负责 Session 级执行监督、Target/Policy 调用、状态写回。Runtime watchdog 随 Agent 自动启动；远端 target/policy server 按需单独部署。

两者之间的共享状态通过工作区中的 Markdown 文件表达，不跨层直接 Python 调用。

### 2.2.2 一次典型运行的完整闭环

1. 运行 `paos onboard` 初始化配置与工作区
2. 启动 `paos agent`
3. 用户输入自然语言任务
4. Agent 读取 `TARGETS.md`、`SKILLRUNTIME.md`、`ENVIRONMENT.md` 等文件进行规划
5. Agent 将可执行任务追加到 `SESSIONS.md`
6. WatchdogSupervisor claim pending session，执行 preflight，运行 target/skill
7. 结果写回到 `SESSIONS.md`、`ENVIRONMENT.md`、`LESSONS.md` 及 artifacts 目录

---

## 2.3 安装与环境准备

### 基础要求

- Python 3.11 或更高版本
- Git
- 可访问的 LLM 提供方 API Key 或兼容服务
- Minecraft 场景额外需要：Windows 11 + Minecraft Java 1.20.4 + Node.js + ngrok

### 克隆与安装

```bash
git clone https://github.com/PhyAgentOS/PhyAgentOS.git
cd PhyAgentOS
pip install -e .
```

### CLI 入口

安装后得到 `paos` 命令：

- `paos onboard` — 初始化工作区
- `paos agent` — 启动交互式 Agent
- `paos agent -m "..."` — 单轮消息调用
- `paos minecraft` — Minecraft 游戏控制命令

---

## 2.4 5 分钟快速开始

### 第 1 步：安装

```bash
git clone https://github.com/PhyAgentOS/PhyAgentOS.git && cd PhyAgentOS
pip install -e .
```

### 第 2 步：初始化工作区

```bash
paos onboard
```

该命令会：创建 `~/.PhyAgentOS/config.json`、准备默认工作区、同步模板文件。

### 第 3 步：配置 API Key

编辑 `~/.PhyAgentOS/config.json`，至少配置：

```json
{
  "agents": {
    "defaults": {
      "model": "openrouter/openai/gpt-4o-mini"
    }
  },
  "providers": {
    "openrouter": {
      "api_key": "YOUR_API_KEY"
    }
  }
}
```

### 第 4 步：启动 Agent

```bash
paos agent
```

进入交互模式后，直接输入自然语言任务。如果只想单次调用：

```bash
paos agent -m "使用 dummy_sim target 运行一次冒烟测试"
```

---

## 2.5 配置详解

### 最小配置

```json
{
  "agents": {
    "defaults": {
      "model": "openrouter/openai/gpt-4o-mini"
    }
  },
  "providers": {
    "openrouter": {
      "api_key": "YOUR_API_KEY"
    }
  }
}
```

配置位置：`~/.PhyAgentOS/config.json`

### 关键配置域

| 配置域 | 用途 |
|--------|------|
| `agents.defaults` | 默认模型、工作区路径 |
| `providers` | LLM 提供方 API Key 与地址 |
| `runtime` | Runtime workspace 配置（enable / workspace 路径） |

### Runtime 配置示例

```json
{
  "runtime": {
    "enabled": true,
    "workspace": "~/.PhyAgentOS/runtime_workspace"
  }
}
```

当 `runtime.enabled` 为 `true` 时，Agent 会：
1. 创建/刷新 runtime workspace
2. 同步 `TARGETS.md`、`SKILLRUNTIME.md`、`SESSIONS.md` 模板
3. 启动 Session Watchdog

---

## 2.6 场景使用指南

### 2.6.1 DummySimTarget 冒烟测试

最快的验证方式——零外部依赖：

```bash
paos agent -m "使用 dummy_sim target 运行一次冒烟测试"
```

DummySimTarget 是一个全模拟的本地 Target，不连接任何外部服务。它返回 numpy 零数组作为观测，执行 5 步后自动返回 success。适合验证 Agent → Runtime 全链路是否打通。

### 2.6.2 Minecraft Game Agent

PhyAgentOS-G 的首个 Game Target，已完整打通全链路。

#### 架构概览

```
[Windows 11]                              [Linux 云端]
  Minecraft ← mineflayer bridge           PhyAgentOS-G Agent
       ↑           ↑                            ↑
  localhost:25565  localhost:3001               │
                   ngrok → HTTPS → MinecraftTarget (HTTP client)
                                           ↑
                                   WatchdogSupervisor
```

**关键设计**：MinecraftTarget 不包含任何 Minecraft 协议代码，仅通过 HTTP 与外部 mineflayer bridge 通信。

#### Windows 端部署（详细步骤）

完整部署指南：[Minecraft 部署文档](../../scenarios/game/minecraft/zh/deployment.md)

最简启动：

```powershell
cd mc_bridge
$env:MC_HOST="localhost"; $env:MC_PORT="25565"; $env:BOT_NAME="paos"
$env:MC_VERSION="1.20.4"; $env:API_PORT="3001"
node bridge_server.js

# 另开终端
ngrok http 3001 --region=ap
```

记录 ngrok 显示的 HTTPS URL（如 `https://xxxx.ngrok-free.app`）。

#### Linux 端配置

编辑 runtime workspace 中的 `TARGETS.md`，添加 Minecraft target：

```yaml
version: targets_v1
targets:
  - id: target://minecraft
    kind: game
    enabled: true
    adapter: target_adapter://minecraft/v1
    config:
      bridge_url: "https://xxxx.ngrok-free.app"
      verify_ssl: false
    supported_skillruntimes:
      - skillruntime://minecraft_game/v1
```

编辑 `SKILLRUNTIME.md`，注册 Minecraft skill runtime：

```yaml
version: skillruntimes_v1
skillruntimes:
  - id: skillruntime://minecraft_game/v1
    kind: builtin
    module: PhyAgentOS.runtime.skillruntime.game.minecraft_skill_runtime
    class: MinecraftSkillRuntime
```

#### 使用

```bash
# CLI 直接控制
paos minecraft say "挖5个橡木然后过来"

# 通过 Agent 下发任务
paos agent -m "让 Minecraft bot 挖10个橡木并合成工作台"
```

#### 动作空间

支持 16 种动作类型：`move`、`look`、`jump`、`sneak`、`sprint`、`attack`、`interact`、`place`、`dig`、`use`、`select_slot`、`drop`、`chat`、`collect`、`equip`、`craft`。

### 2.6.3 LIBERO Benchmark 仿真验证

LIBERO 是标准的机器人操作 Benchmark，PhyAgentOS-G 通过 TargetWS 远程协议支持。

#### 启动服务

```bash
# TargetWS 机器（需 LIBERO 环境）
MUJOCO_GL=egl PYTHONWARNINGS=ignore \
python PhyAgentOS/runtime/targets/remote/libero/server.py \
  --host 0.0.0.0 --port 9002

# Policy 机器（需 pi0.5 checkpoint）
python -m PhyAgentOS.runtime.policy.openpi.lerobot_pi0_server \
  --model-dir /path/to/pi05/checkpoint --host 0.0.0.0 --port 8000
```

#### 运行 E2E 验证

```bash
python scripts/run_pi05_libero_real_e2e.py \
  --policy-endpoint openpi://127.0.0.1:8000 \
  --target-endpoint targetws://127.0.0.1:9002 \
  --benchmark-name libero_spatial --task-id 0
```

或通过 Agent：
```bash
paos agent -m "运行已配置的 LIBERO benchmark 任务"
```

---

## 2.7 运行时文件说明

| 文件 | 所属工作区 | 功能 |
|------|------|------|
| `AGENTS.md` | Agent workspace | 项目级运行规则 |
| `SOUL.md` | Agent workspace | 身份与助手行为 |
| `USER.md` | Agent workspace | 用户偏好与长期画像 |
| `SKILLS.md` | Agent workspace | Agent skill 发现与加载规则 |
| `EMBODIED.md` | Agent workspace | Target 能力的人类可读描述 |
| `ENVIRONMENT.md` | Agent/runtime workspace | 当前 target、场景、对象与环境状态 |
| `LESSONS.md` | Agent workspace | 运行经验与失败记录 |
| `TASK.md` | Agent workspace | 多步任务拆解状态 |
| `TARGETS.md` | Runtime workspace | Target 注册、endpoint、adapter、config |
| `SKILLRUNTIME.md` | Runtime workspace | Skill runtime 注册表与执行契约 |
| `SESSIONS.md` | Runtime workspace | Session 队列与执行结果 |

---

## 2.8 常见交互示例

### DummySimTarget 冒烟

```bash
paos agent -m "使用 dummy_sim target 运行一次冒烟测试"
```

验证 Agent → Runtime 全链路是否打通。

### Minecraft 自然语言控制

```bash
paos minecraft say "挖5个橡木然后过来"
```

LLM 自动将自然语言转为 Minecraft 16 种动作序列执行。

### Minecraft 游戏内聊天控制

在游戏聊天中对 bot 下达指令：
```text
paos 挖5个橡木
```

### LIBERO Benchmark 评测

```bash
python scripts/run_pi05_libero_sweep.py --benchmark-name libero_spatial
```

批量运行多个 LIBERO task 并收集结果。

---

## 2.9 常见问题排查

### 提示没有 API Key

1. 检查 `~/.PhyAgentOS/config.json` 是否配置了 `providers.<name>.api_key`
2. 确认 `agents.defaults.model` 与对应 provider 配套
3. API Key 格式正确，无多余空格

### Runtime 协议文件缺失

1. 确认 config 中 `runtime.enabled` 为 `true`
2. 检查 `runtime.workspace` 路径
3. 启动 `paos agent`，或手动初始化：
   ```bash
   python scripts/init_runtime_workspace.py --workspace <path>
   ```

### SESSIONS.md 有 pending 但没有执行

1. 确认 WatchdogSupervisor 仍在运行（随 Agent 自动启动）
2. 检查 session 的 `target_ref` 与 `skillruntime_ref` 是否存在于 `TARGETS.md` / `SKILLRUNTIME.md`
3. 检查 target 是否 `enabled: true`
4. 查看 Agent 日志中的 preflight 错误

### Session 被 preflight 拒绝

1. 查看 `SESSIONS.md` 中该 session 的 result/error
2. 检查 target 是否支持该 `skillruntime_ref`
3. 检查 `SKILLRUNTIME.md` 中 observation/action contract 是否与 target runtime contract 兼容

### Minecraft bridge 连接失败（SSL 错误）

1. ngrok 免费版证书不完整，在 TARGETS.md 配置中添加 `"verify_ssl": false`
2. 确认 bridge_url 前后无多余空格

### Minecraft API 返回空或 HTML

1. ngrok 免费版会先显示确认页，在 `minecraft_target.py` 中已添加 `ngrok-skip-browser-warning: true` header
2. 检查 ngrok 隧道是否仍在运行
3. 确认 bridge URL 包含 `https://` 前缀

### Minecraft bot 传送不生效

1. 确认世界开启作弊（Esc → 对局域网开放 → 允许作弊: 开）
2. 玩家需在 bot 的 render distance 范围内

---

## 后续阅读

- [Part 1: 框架介绍](01-framework-introduction.md) — 设计理念、架构、路线图
- [Part 3: 开发者手册](03-developer-manual.md) — 接口文档、Target/Adapter/Skill 开发
- [Minecraft 部署指南](../scenarios/game/minecraft/zh/deployment.md) — 完整部署流程

> **下一步**：如果需要添加新游戏或自定义 Target，进入 [开发者手册](03-developer-manual.md)。
