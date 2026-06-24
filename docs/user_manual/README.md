# PhyAgentOS 用户手册

> 面向使用者、集成者与演示操作者的运行手册。本文档基于当前仓库结构整理，重点覆盖单机模式、Fleet 多机器人模式、驱动启动方式、工作区文件职责，以及真实机器人插件接入路径。

## 目录

- [1. 手册定位与阅读路径](#1-手册定位与阅读路径)
- [2. 先理解系统是如何工作的](#2-先理解系统是如何工作的)
- [3. 安装与环境准备](#3-安装与环境准备)
- [4. 首次初始化：配置文件与工作区](#4-首次初始化配置文件与工作区)
- [5. 单机模式快速开始](#5-单机模式快速开始)
- [6. 常用运行方式总览](#6-常用运行方式总览)
- [7. 内置驱动、示例配置与真实机器人插件](#7-内置驱动示例配置与真实机器人插件)
- [8. Fleet 模式：多机器人协同运行](#8-fleet-模式多机器人协同运行)
- [9. 运行时 Markdown 文件职责](#9-运行时-markdown-文件职责)
- [10. 常见交互与操作示例](#10-常见交互与操作示例)
- [11. 常见问题与排查建议](#11-常见问题与排查建议)
- [12. 未来章节（开发中）](#12-未来章节开发中)

## 1. 手册定位与阅读路径

### 1.1 这份手册适合谁

本文档主要面向以下读者：

- 希望快速跑通 PhyAgentOS 的首次使用者
- 需要用命令行或网关方式操作 Agent 的集成使用者
- 需要启动仿真、Go2、远程底盘或真实机器人插件的演示操作者
- 需要理解运行时工作区文件如何变化的调试人员

如果你要进行二次开发、编写驱动、开发插件或研究系统内部架构，请优先继续阅读 [USER_DEVELOPMENT_GUIDE.md](../user_development_guide/README.md)。

### 1.2 文档地图

| 文档 | 用途 | 何时阅读 |
| --- | --- | --- |
| [../README_zh.md](../../README_zh.md) | 项目总览、特性与展示入口 | 第一次了解项目时 |
| [COMMUNICATION.md](../user_development_guide/COMMUNICATION.md) | 运行时通信架构、工作区拓扑与文件职责说明 | 想理解 Track A / Track B 与共享状态时 |
| [USER_DEVELOPMENT_GUIDE.md](../user_development_guide/README.md) | 面向开发者的二次开发与扩展指南 | 需要改代码、接新硬件或做插件时 |
| [phyagentos-rekep-plugin-blog-zh.md](../user_development_guide/REKEP_PLUGIN_DEPLOYMENT_zh.md) | ReKep 真实机器人插件的一键部署、联调与执行说明 | 想尽快接入 `rekep_real` 时 |
| [PLUGIN_DEVELOPMENT_GUIDE_zh.md](../user_development_guide/PLUGIN_DEVELOPMENT_GUIDE_zh.md) | 外部插件开发模板（中文） | 想按模板开发独立插件仓库时 |
| [PLUGIN_DEVELOPMENT_GUIDE.md](../user_development_guide/PLUGIN_DEVELOPMENT_GUIDE.md) | 外部插件开发模板（英文） | 需要英文材料或对外发布时 |
| [plans/Report.md](../plans/Report.md) | 项目规划与报告类文档 | 想了解后续方向时 |
| [changelog/v0.0.5.md](../changelog/v0.0.5.md) | 历史变更记录参考 | 想了解某阶段设计演进时 |

## 2. 先理解系统是如何工作的

### 2.1 双轨结构：Track A 与 Track B

PhyAgentOS 不是“LLM 直接调用硬件接口”的黑盒控制系统，而是一个显式解耦的双轨运行架构：

- **Track A（Agent / 大脑）**
  - 负责理解用户输入、规划动作、调用工具、做 Critic 校验
  - 通常通过 [`paos agent`](../../PhyAgentOS/cli/commands.py) 或 [`paos gateway`](../../PhyAgentOS/cli/commands.py) 启动
- **Track B（HAL / 小脑）**
  - 负责 session 级执行监督、target/policy 调用、artifact 与环境状态写回
  - Runtime watchdog 会随 [`paos agent`](../../PhyAgentOS/cli/commands.py) 或 [`paos gateway`](../../PhyAgentOS/cli/commands.py) 自动启动；远端 target/policy server 按需单独部署

两者之间的共享状态优先通过工作区中的 Markdown 文件表达，而不是跨层直接 Python 调用。更完整的通信解释见 [COMMUNICATION.md](../user_development_guide/COMMUNICATION.md)。

### 2.2 单机模式与 Fleet 模式

PhyAgentOS 有两种典型运行拓扑：

1. **单机模式（single）**
   - 默认工作区通常位于 `~/.PhyAgentOS/workspace`
   - 适合单个机器人或仿真快速验证
2. **Fleet 模式（fleet）**
   - 共享工作区通常位于 `~/.workspaces/shared`
   - 每个机器人实例都有自己的工作区
   - 适合异构多机器人协同

### 2.3 一次典型运行会发生什么

一个标准闭环通常如下：

1. 运行 `paos onboard` 初始化配置与工作区
2. 启动 `paos agent` 或 `paos gateway`
3. Agent 自动创建/刷新 runtime workspace，并启动 session watchdog
4. 用户输入自然语言任务
5. Agent 读取 `TARGETS.md`、`SKILLRUNTIME.md`、`ENVIRONMENT.md` 等工作区文件进行规划
6. Agent 将可执行任务追加到 `SESSIONS.md`
7. Watchdog claim pending session，执行 preflight、运行 target/skill，并写回 result、artifact 与环境状态

## 3. 安装与环境准备

### 3.1 基础要求

建议至少准备以下环境：

- Python 3.11 或更高版本
- Git
- 可访问的 LLM 提供方 API 或兼容服务
- 如需仿真：建议额外准备 `pybullet`
- 如需桥接、前端或部分渠道能力：建议准备 Node.js 18+

### 3.2 克隆与安装

如果你使用主仓库，可以直接执行：

```bash
git clone https://github.com/SYSU-HCP-EAI/PhyAgentOS.git
cd PhyAgentOS
pip install -e .
```

如果你准备使用仿真机械臂，通常还需要：

```bash
pip install pybullet
```

### 3.3 安装完成后你会得到什么

安装后，CLI 入口 `paos` 会来自项目的 Python 包入口。常见使用命令包括：

- `paos onboard`
- `paos agent`
- `paos gateway`
- `python scripts/init_runtime_workspace.py --workspace <path>`（开发/验收时手动生成 runtime 协议文件）
- `python hal/hal_watchdog.py --driver simulation`（legacy HAL driver 调试）

## 4. 首次初始化：配置文件与工作区

### 4.1 执行初始化

首次使用请先运行：

```bash
paos onboard
```

该命令会完成以下工作：

- 创建或刷新 `~/.PhyAgentOS/config.json`
- 在单机模式下准备默认工作区
- 在 Fleet 模式下准备共享工作区与机器人工作区布局
- 同步工作区模板文件

如果你升级过项目版本，重新执行一次 `paos onboard` 也很有价值，因为它会刷新配置模板并补充新字段。

### 4.2 最少需要配置什么

最小可用配置通常至少包含：

- `agents.defaults.model`
- 某个 `providers.*.api_key`

一个最小示意配置如下：

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

如果你使用自定义 OpenAI 兼容接口，可以改为配置 `providers.custom.api_base` 与对应 `api_key`。

### 4.3 默认工作区在哪里

- **单机模式**：`~/.PhyAgentOS/workspace`
- **Fleet 模式共享工作区**：`~/.workspaces/shared`
- **Fleet 模式机器人工作区**：`~/.workspaces/<robot_id>`

## 5. 单机模式快速开始

以下流程适合第一次跑通系统。

### 5.1 第一步：初始化工作区

```bash
paos onboard
```

### 5.2 第二步：启动 Agent

运行：

```bash
paos agent
```

进入交互模式后，你可以直接输入自然语言任务。

如果你只想单次调用，也可以使用：

```bash
paos agent -m "看看桌面上有什么物体"
```

### 5.3 第三步：连接远程 runtime 服务

如果任务需要远程仿真或真实策略服务，先在对应机器启动 target/policy server。例如 LIBERO + pi0.5：

```bash
MUJOCO_GL=egl PYTHONWARNINGS=ignore \
conda run -n liberopi python PhyAgentOS/runtime/targets/remote/libero/server.py \
  --host 0.0.0.0 --port 9002

conda run -n lerobot-pi python -m PhyAgentOS.runtime.policy.openpi.lerobot_pi0_server \
  --model-dir /path/to/pi05/checkpoint --host 0.0.0.0 --port 8000
```

### 5.4 第四步：观察文件变化

第一次调试时，建议同时关注这些文件：

- `TARGETS.md`：target 是否启用、endpoint 是否正确
- `SKILLRUNTIME.md`：目标 skill runtime 是否存在
- `SESSIONS.md`：Agent 是否追加 pending session，watchdog 是否写回结果
- `ENVIRONMENT.md`：target/runtime 是否写回环境状态
- `LESSONS.md`：preflight 或执行失败时是否记录经验

## 6. 常用运行方式总览

### 6.1 命令速查表

| 目标 | 命令 | 说明 |
| --- | --- | --- |
| 初始化配置与工作区 | `paos onboard` | 首次运行或升级后刷新模板 |
| 交互式命令行对话 | `paos agent` | 适合本地直接调试 |
| 单轮发送消息 | `paos agent -m "..."` | 适合脚本化或快速 smoke test |
| 启动网关 | `paos gateway` | 适合渠道接入、定时任务与心跳服务 |
| 初始化 runtime workspace | `python scripts/init_runtime_workspace.py --workspace <path>` | 开发/验收时手动生成协议文件 |
| 启动 LIBERO target server | `python PhyAgentOS/runtime/targets/remote/libero/server.py ...` | 在已安装 LIBERO 的机器上运行 |
| 启动 pi0.5 policy server | `python -m PhyAgentOS.runtime.policy.openpi.lerobot_pi0_server ...` | 在已安装 LeRobot 与权重的环境运行 |

### 6.2 什么时候用 `paos agent`

`paos agent` 适合：

- 本地 CLI 调试
- 快速验证工作区、Agent 和 Watchdog 是否打通
- 开发期间观察工具调用与 Critic 行为

### 6.3 什么时候用 `paos gateway`

`paos gateway` 更适合：

- 接入聊天渠道
- 使用心跳服务、定时任务与会话管理
- 将 Agent 放到“长期在线服务”形态运行

如果配置中没有启用渠道，`paos gateway` 仍可启动，但它更适合作为服务化入口而非本地交互入口。

## 7. 内置驱动、示例配置与真实机器人插件

### 7.1 当前仓库中常见的启动目标

| 类型 | 驱动名 | 状态 | 说明 |
| --- | --- | --- | --- |
| 内置仿真 | `simulation` | 可直接使用 | 最适合首次跑通 |
| 内置移动机器人 | `go2_edu` | 需准备真实配置 | 适合导航、定位与目标导航相关实验 |
| 内置远程底盘 | `xlerobot_2wheels_remote` | 需准备远程主机配置 | 通过 ZMQ 控制远程底盘 |
| 内置机械臂 | `franka_research3` | 需准备 Control Box 配置 | 通过 pylibfranka 控制 FR3 机械臂 |
| 外部插件 | `rekep_real` | 需先安装插件 | 适合真实机械臂 ReKep 运行 |

### 7.2 Go2 示例

仓库已提供一个驱动配置示例：[../examples/go2_driver_config.json](../../examples/go2_driver_config.json)。

典型启动方式：

```bash
python hal/hal_watchdog.py \
  --driver go2_edu \
  --driver-config examples/go2_driver_config.json
```

这个 JSON 配置会透传给 Go2 驱动，用于远程 ROS2、视频、状态流和运动后端初始化。

### 7.3 XLerobot 远程底盘示例

仓库也提供了远程底盘配置示例：[../examples/xlerobot_2wheels_remote.driver.json](../../examples/xlerobot_2wheels_remote.driver.json)。

典型启动方式：

```bash
python hal/hal_watchdog.py \
  --driver xlerobot_2wheels_remote \
  --driver-config examples/xlerobot_2wheels_remote.driver.json
```

### 7.4 Franka Research 3 机械臂示例

Franka Research 3 (FR3) 支持两种驱动模式：

#### 7.4.1 驱动选择

| 驱动名 | 说明 | 适用场景 |
|:-------|:-----|:---------|
| `franka_research3` | 原始 pylibfranka 驱动 | 需要精确控制或实时 1kHz |
| `franka_multi` | 多后端协商驱动 | 自动选择可用后端，更好的兼容性 |

#### 7.4.2 网络架构

```
WorkStation PC --> Control Box (Shop Floor: 172.16.0.x) --> Robot Arm (内部网络)
```

#### 7.4.3 首次设置

1. 网线连接 PC ↔ Control Box (Shop Floor 接口)
2. PC 有线网络 IP 设为 `172.16.0.x`（如 `172.16.0.1`）
3. 在 Control Box Desk 界面激活 FCI
4. 安装后端驱动（见下节）

#### 7.4.4 后端安装

推荐同时安装两个后端，系统自动选择：

🚨在安装之前请检查安装的库的版本与机器人系统的版本是否兼容

```bash
# pylibfranka (官方 Python 绑定)
pip install pylibfranka

# franky-control (备选高层库，更宽松的兼容性)
pip install git+https://github.com/TimSchneider42/franky.git
```

#### 7.4.5 启动方式

```bash
# 多后端自动协商（推荐）
python hal/hal_watchdog.py --driver franka_multi

# 原始 pylibfranka 驱动
python hal/hal_watchdog.py --driver franka_research3

# 自定义配置
python hal/hal_watchdog.py \
  --driver franka_multi \
  --driver-config examples/franka_research3.driver.json
```

#### 7.4.6 支持的动作

`move_to`（笛卡尔位置）、`move_joints`（关节位置）、`grasp`、`move_gripper`、`stop` 等。

#### 7.4.7 实时控制模式

设置 `realtime_mode: true` 可启用 1 kHz 实时控制（需安装实时内核）。

详细说明请参考：
- [hal/profiles/franka_research3.md](../../hal/profiles/franka_research3.md)
- [appendix/franka_compatibility.md](appendix/franka_compatibility.md) - 版本兼容性表格
- [appendix/franka_capabilities.md](appendix/franka_capabilities.md) - 后端能力对比
- [appendix/franka_version_guide.md](appendix/franka_version_guide.md) - 有关版本兼容的说明

### 7.5 ReKep 真实机器人插件

`rekep_real` 不是主仓库内置驱动，而是通过外部插件仓库接入。推荐流程如下：

1. 安装主仓库
2. 执行插件部署脚本
3. 启动 Watchdog 时选择 `rekep_real`

示例：

```bash
python scripts/deploy_rekep_real_plugin.py \
  --repo-url https://github.com/baiyu858/PhyAgentOS-rekep-real-plugin.git

python hal/hal_watchdog.py --driver rekep_real
```

与该插件相关的详细文档请继续阅读：

- [phyagentos-rekep-plugin-blog-zh.md](../user_development_guide/REKEP_PLUGIN_DEPLOYMENT_zh.md)
- [PLUGIN_DEVELOPMENT_GUIDE_zh.md](../user_development_guide/PLUGIN_DEVELOPMENT_GUIDE_zh.md)

## 8. Fleet 模式：多机器人协同运行

### 8.1 何时使用 Fleet 模式

当你需要：

- 让一个 Agent 面向多个机器人实例协同规划
- 将共享环境、target registry 与 session 队列分开维护
- 通过 `TARGETS.md`、`SKILLRUNTIME.md` 与 `SESSIONS.md` 管理多个 target 的执行入口

就应该启用 Fleet 模式。

### 8.2 最小 Fleet 配置示意

你可以在 `~/.PhyAgentOS/config.json` 中配置如下结构：

```json
{
  "embodiments": {
    "mode": "fleet",
    "shared_workspace": "~/.workspaces/shared",
    "instances": [
      {
        "robot_id": "go2_edu_001",
        "driver": "go2_edu",
        "workspace": "~/.workspaces/go2_edu_001"
      },
      {
        "robot_id": "xlerobot_lab_001",
        "driver": "xlerobot_2wheels_remote",
        "workspace": "~/.workspaces/xlerobot_lab_001"
      }
    ]
  }
}
```

然后重新执行：

```bash
paos onboard
```

### 8.3 Fleet 模式的启动顺序

推荐顺序如下：

1. 配置 `embodiments.mode = "fleet"`
2. 运行 `paos onboard`
3. 启动 `paos agent` 或 `paos gateway`
4. Runtime workspace 会按配置创建，session watchdog 会在 runtime 启用时自动启动

例如：

```bash
paos agent
```

> Runtime 是否启用、runtime workspace 是否独立，由 config 的 `runtime.enabled` 与 `runtime.workspace` 控制。

### 8.4 Fleet 模式下你会看到哪些文件

- `shared/ENVIRONMENT.md`：全局环境与 target 状态
- `shared/TARGETS.md`：target registry
- `shared/SKILLRUNTIME.md`：可执行 skill runtime registry
- `shared/SESSIONS.md`：session 队列与结果
- `shared/TASK.md`：多步任务状态
- `shared/ORCHESTRATOR.md`：全局编排状态

### 8.5 Fleet 模式下的交互注意事项

在多机器人模式下，面向具身动作的请求通常需要明确目标机器人。简而言之：

- 用户指令应尽量说明“由哪台机器人执行”
- target 是否启用、支持哪些 skill runtime，以 `TARGETS.md` 为准
- `TARGETS.md`、`SESSIONS.md` 与 `ENVIRONMENT.md` 是理解当前编队状态的第一入口

## 9. 运行时 Markdown 文件职责

下表是日常使用最值得理解的一组文件：

| 文件 | 典型位置 | 作用 |
| --- | --- | --- |
| `SKILLS.md` | Agent workspace | 面向 Agent 的 skill 发现与加载规则 |
| `EMBODIED.md` | Agent workspace | Target 能力的人类可读描述 |
| `ENVIRONMENT.md` | Agent/runtime workspace | 当前 target、场景、对象与环境状态 |
| `LESSONS.md` | Agent workspace | 运行经验与失败记录 |
| `TASK.md` | Agent workspace | 多步任务拆解状态 |
| `TARGETS.md` | Runtime workspace | Target registry 与 endpoint/adapter/config 引用 |
| `SKILLRUNTIME.md` | Runtime workspace | 可执行 skill runtime registry 与执行契约 |
| `SESSIONS.md` | Runtime workspace | 执行 session 队列与结果 |
| `ORCHESTRATOR.md` | Agent workspace | 编排层状态 |

如果你想进一步理解这些文件如何在不同模式下协同，请阅读 [COMMUNICATION.md](../user_development_guide/COMMUNICATION.md)。

## 10. 常见交互与操作示例

### 10.1 环境查询

```text
看看当前环境里有什么物体。
```

适合验证：

- Agent 是否能读取 `ENVIRONMENT.md`
- 当前环境状态是否已由 Watchdog 正确写回

### 10.2 机械臂抓取/操作类任务

```text
把桌上的红色苹果拿起来，放到托盘里。
```

适合验证：

- 目标物体是否已出现在环境状态中
- `TARGETS.md` 是否启用了对应 target
- `SKILLRUNTIME.md` 是否声明了兼容的 policy/builtin runtime
- Watchdog 是否成功执行 session 并在 `SESSIONS.md` 写回结果

### 10.3 移动机器人导航类任务

```text
移动到冰箱附近并停下。
```

适合验证：

- 场景图或地图中是否存在目标语义位置
- 当前移动机器人是否支持导航或目标导航动作

### 10.4 Fleet 多机器人协同任务

```text
让 Go2 先去门口巡检，再让机械臂把桌上的包裹抓起来准备交接。
```

适合验证：

- Agent 是否识别多个机器人实例
- session 是否绑定到正确 target
- `SESSIONS.md` 与 `ENVIRONMENT.md` 是否正确更新状态

## 11. 常见问题与排查建议

### 11.1 提示没有 API Key

现象：启动 `paos agent` 或 `paos gateway` 后报没有 API key。

排查建议：

- 检查 `~/.PhyAgentOS/config.json`
- 确认 `agents.defaults.model` 与对应 provider 配套
- 确认正确填写了 `providers.<name>.api_key`

### 11.2 Runtime 启动后没有协议文件

现象：找不到 `TARGETS.md`、`SKILLRUNTIME.md` 或 `SESSIONS.md`。

排查建议：

- 确认 config 中 `runtime.enabled` 为 `true`
- 确认 `runtime.workspace` 是否指向独立目录
- 启动 `paos agent` / `paos gateway`，或用 `python scripts/init_runtime_workspace.py --workspace <path>` 手动初始化
- 若使用 Fleet 模式，确认你查看的是 shared/runtime workspace

### 11.3 `SESSIONS.md` 有 pending 但没有执行

排查建议：

- 确认对应 Watchdog 仍在运行
- 检查 session 的 `target_ref` 与 `skillruntime_ref` 是否存在
- 检查 `TARGETS.md` 中 target 是否 `enabled: true`
- 查看 Watchdog 终端日志是否出现 preflight 或 runtime 错误
- 检查 runtime contract、sensor config、policy endpoint 是否缺失

### 11.4 Session 被 preflight 拒绝

现象：session 状态变成 `rejected`。

排查建议：

- 先查看 `SESSIONS.md` 中该 session 的 result/error
- 检查 target 是否支持该 `skillruntime_ref`
- 检查 `SKILLRUNTIME.md` 中 observation/action contract 是否与 target contract 兼容
- 检查 `ENVIRONMENT.md` 中是否存在必要目标物体、地图信息或连接状态

### 11.5 Fleet 模式下任务没有派发到正确机器人

排查建议：

- 检查配置中的 `robot_id`、`driver`、`workspace` 是否匹配
- 检查 `TARGETS.md` 中的 target id、workspace 与 enabled 状态
- 检查 `SESSIONS.md` 中 session 的 `target_ref`
- 确认任务语义里明确了目标机器人

### 11.6 找不到 `rekep_real` 驱动

排查建议：

- 确认已经执行插件部署脚本
- 确认插件仓库已注册到本地插件目录
- 优先参考 [phyagentos-rekep-plugin-blog-zh.md](../user_development_guide/REKEP_PLUGIN_DEPLOYMENT_zh.md) 的完整部署步骤

## 12. 未来章节（开发中）

以下主题建议后续继续扩展为独立专题文档；当前先在总手册中预留条目：

### 12.1 ROS2 深度接入（开发中）

计划补充：导航、TF、地图、桥接与适配器的完整说明。

### 12.2 多模态感知部署（开发中）

计划补充：几何管线、语义分割、融合与环境写回的部署清单。

### 12.3 长程任务与编排（开发中）

计划补充：`TASK.md`、`ORCHESTRATOR.md`、Heartbeat、Cron 的协同使用方式。

### 12.4 渠道接入操作手册（开发中）

计划补充：Telegram、Feishu、Slack、WhatsApp 等渠道的最小配置与排障流程。

### 12.5 多机器人实战案例（开发中）

计划补充：面向 Go2、机械臂、远程底盘的组合任务样例与推荐调试路径。

---

如果你的目标已经从“使用系统”转向“扩展系统”，下一站应当是 [USER_DEVELOPMENT_GUIDE.md](../user_development_guide/README.md)。
