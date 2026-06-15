# Stardew Valley Target 部署文档

## 架构概览

```
[Windows 11]
  Stardew Valley + SMAPI
       ↑ localhost:10783
  StardojoMod                         ← 游戏内 Mod，接收动作/返回状态
       ↑ localhost:8765 (HTTP API)
  PhyAgentOS Stardew bridge           ← Python bridge，复用 StarDojo API
       ↓

[Windows / WSL / Linux - PhyAgentOS]
  Agent (Track A ReAct / tool-calling)
       ↑
  Stardew tools                       ← stardew_action / stardew_observe 正式 Track A tools
       ↑
  StardewValleyTargetAdapter          ← target_adapter://stardewvalley_adapter
       ↑
  后续可扩展 SkillRuntime / WatchdogSupervisor
```

**关键设计**：
- Stardew bridge 已放入 OS 内部：`runtime/adapters/stardewvalley/bridge/`
- StarDojo 需要从官方仓库下载至：`runtime/adapters/stardewvalley/`
- OS 当前通过 HTTP 调用 bridge，不直接嵌入 SMAPI 协议
- 手动控制可以让 Agent 通过 exec/curl 调 bridge
- benchmark supervisor 启动正常 `paos agent`，由正式 Track A tools 驱动 bridge
- V1 是 ReAct-style：每次执行一个基础动作，动作后立即返回新的 observation/evaluator 状态
- 当前不是 Minecraft-style 的 `SESSIONS.md + WatchdogSupervisor + SkillRuntime` 完整 pipeline

---

## 一、环境要求

| 组件 | 位置 | 说明 |
|------|------|------|
| Stardew Valley | Windows 11 | Steam/GOG 版本均可 |
| SMAPI | Windows 11 | 必须通过 `StardewModdingAPI.exe` 启动游戏 |
| StardojoMod | Windows 11 | 放入 Stardew Valley 的 `Mods` 目录，监听 10783 |
| micromamba | Windows 11 | 创建 `stardojo` 环境 |
| Python | Windows 11 | 推荐 3.11 |
| PhyAgentOS | WSL/Linux 或 Windows | Agent 侧，通过 HTTP bridge 控制游戏 |
| starlette/uvicorn | Windows 11 | bridge HTTP server 依赖 |

---

## 二、代码位置

当前 Stardew 相关代码集中在 PhyAgentOS adapter 目录：

```text
PhyAgentOS/PhyAgentOS/runtime/adapters/stardewvalley/
  bridge/
    action_parser.py       # 安全解析 action 字符串
    obs_compact.py         # 压缩 StarDojo observation，转 JSON-safe
    stardew_runtime.py     # StarDojo runtime wrapper，串行 observe/execute
    bridge_server.py       # Starlette/uvicorn HTTP API
  target_adapter.py        # PhyAgentOS adapter，注册为 stardewvalley_adapter
  tests/                   # bridge 单元测试
  Stardew Valley README.md # 本部署文档
```

adapter 已注册：

```text
target_adapter://stardewvalley_adapter
```

---

## 三、Windows 11 端部署

### 3.1 安装 Stardew Valley + SMAPI

1. 安装 Stardew Valley 游戏本体。
2. 安装 SMAPI：https://smapi.io/
3. 确认可以通过下面的程序启动游戏：

```text
StardewModdingAPI.exe
```

不要直接启动：

```text
Stardew Valley.exe
```

### 3.2 安装 StardojoMod

下载编译好的 StardojoMod ，然后放入 Stardew Valley 的 `Mods` 目录。
下载链接：
```text
https://github.com/StarDojo2025/stardojo#:~:text=Download%20StarDojoMod%20from%20Nexus%20Mods
```

启动游戏后，SMAPI 控制台应显示 StardojoMod 已加载，并监听：

```text
127.0.0.1:10783
```

### 3.3 创建 Python 环境

```powershell
micromamba create -n stardojo python=3.11
micromamba activate stardojo
```

安装 bridge 依赖：

```powershell
pip install starlette uvicorn
```

安装 StarDojo 仓库和依赖：

```powershell
cd ".\PhyAgentOS\runtime\adapters\stardewvalley"
git clone https://github.com/StarDojo2025/stardojo.git
cd ./stardojo
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```
注意：
| 问题 | 修复 |
|------|------|
| `requirements.txt` 中包含 `stardojo==0.1` | 注释掉`stardojo==0.1` |
| `setup.ps1` 中 `Join-Path $PSScriptRoot "agent" "stardojo"` 报错 | 改为 `Join-Path (Join-Path $PSScriptRoot "agent") "stardojo"` |

### 3.4 启动 Stardew Valley

必须完成以下状态后再启动 bridge：

```text
1. 通过 StardewModdingAPI.exe 启动游戏
2. SMAPI 控制台显示 StardojoMod 已加载
3. 游戏已经进入一个存档
4. StardojoMod 正在监听 127.0.0.1:10783
```

### 3.5 启动 Stardew bridge

在 Windows PowerShell：

```powershell
micromamba activate stardojo
python -m PhyAgentOS.runtime.adapters.stardewvalley --host 0.0.0.0 --port 8765 --stardojo-port 10783
```

参数说明：

| 参数 | 说明 |
|------|------|
| `--host 0.0.0.0` | 允许 WSL 或局域网访问 |
| `--port 8765` | Stardew bridge HTTP 端口 |
| `--stardojo-port 10783` | SMAPI StardojoMod 端口 |
| `--stardojo-root` | 默认使用 adapter 内置 `stardojo/`，通常不用传 |

---

## 四、Windows 端验证

### 4.1 健康检查

```powershell
curl http://127.0.0.1:8765/health
```

期望输出：

```json
{"ok":true,"stardojo_port":10783}
```

### 4.2 获取 observation

```powershell
curl http://127.0.0.1:8765/observe
```

响应格式：

```json
{
  "ok": true,
  "obs": {
    "location": "Farm",
    "position": [62, 17],
    "latest_image_url": "http://127.0.0.1:8765/images/latest"
  }
}
```

## 五、WSL / Linux 端验证

如果 WSL 配了代理，curl 可能走代理导致超时。统一加：

```bash
--noproxy '*'
```

### 5.1 快速测试

```bash
curl --noproxy '*' http://127.0.0.1:8765/health
curl --noproxy '*' --max-time 30 http://127.0.0.1:8765/observe
curl --noproxy '*' http://127.0.0.1:8765/images/latest --output latest.jpeg
curl --noproxy '*' -X POST http://127.0.0.1:8765/execute \
  -H "Content-Type: application/json" \
  -d '{"action":"move(1, 0)"}'
```

---

## 六、Observation 空间

默认 compact observation 字段：

```python
{
    "basic_knowledge": {},
    "health": 100,
    "energy": 270,
    "money": 500,
    "location": "Farm",
    "position": [62, 17],
    "facing_direction": "down",
    "inventory": [],
    "chosen_item": {},
    "time": "06:10",
    "day": 1,
    "season": "spring",
    "farm_animals": [],
    "farm_pets": [],
    "farm_buildings": [],
    "surroundings": [],
    "crops": [],
    "exits": [],
    "buildings": [],
    "furniture": [],
    "npcs": [],
    "shop_counters": [],
    "current_menu": {},
    "latest_image_url": "http://127.0.0.1:8765/images/latest",
}
```

说明：
- `latest_image_url` 是 bridge 暴露的最近截图 HTTP 地址
- `image_paths`、`ScreenShot`、`screenshot` 不进入默认响应，避免 HTTP JSON 序列化和跨系统路径问题
- `current_menu` 不一定能识别所有 UI，例如地图可能已打开但仍显示 `No Menu`

---

## 七、动作空间

所有动作通过 `POST /execute` 发给 bridge，格式是 Python 风格函数调用字符串。

安全限制：
- 只允许白名单动作
- 参数必须是 `ast.literal_eval` 可解析的字面量
- 字符串必须加引号，例如 `use("down")`
- 不允许属性调用，例如 `executor.move(1, 0)`
- 不允许嵌套调用，例如 `move(get_x(), 0)`

### 移动

```python
move(1, 0)    # 向右移动 1 格
move(-1, 0)   # 向左移动 1 格
move(0, 1)    # 向下移动 1 格
move(0, -1)   # 向上移动 1 格
```

### 工具使用与交互

```python
use("up")
use("right")
use("down")
use("left")

interact("up")
interact("right")
interact("down")
interact("left")
```

### 物品与合成

```python
choose_item(0)
craft("Chest")
attach_item(3)
unattach_item()
```

### 菜单与选项

```python
menu("open", "map")
menu("close", "current_menu")
choose_option(1, 1, "in")
choose_option(1, 1, "out")
```

无效示例：

```python
use(down)              # 错，字符串未加引号
open_map()             # 错，不在白名单
executor.move(1, 0)    # 错，属性调用
move(get_x(), 0)       # 错，嵌套调用
```

---

## 八、让 Agent 控制 Stardew

当前 V1 没有完整接入 Minecraft 那套 `SESSIONS.md + WatchdogSupervisor + SkillRuntime`。推荐方式是让 Agent 使用 exec/curl 调 bridge。

```bash
paos agent
```

输入：

```text
你现在控制 Stardew Valley。Bridge 是 http://127.0.0.1:8765。请用 exec 调用 /observe 观察，用 /execute 执行动作。先观察当前状态，并告诉我玩家位置、时间、背包和周围环境。不要使用 HAL watchdog。
```

继续输入：

```text
向左移动，直到遇到草，然后把草割掉。
```

执行方式是：

```text
observe -> execute 一个基础动作 -> 读取新 obs -> 再决定下一步 -> 直到任务完成
```
---

## 九、Benchmark 任务评测

这一版把 Stardew action 接成正式 Track A tool，并把 `paos stardew benchmark` 改成 supervisor。benchmark CLI 不再自己创建 AgentLoop；它只负责初始化 case、启动正常 `paos agent`、等待 agent 通过工具完成任务、最后汇总日志。

整体流程：

```text
paos stardew benchmark
-> bridge /benchmark/start 初始化 task、存档和 init_commands
-> supervisor 启动正常 paos agent -m "<task prompt>"
-> 正常 AgentLoop 根据环境变量注册正式 Stardew tools
-> agent 调用 stardew_action(action="...")
-> stardew_action 内部调 bridge /benchmark/execute
-> bridge 执行动作、observe、调用 StarDojo evaluator
-> tool result 只返回 obs + done/truncated/step 停止信号
-> evaluator 细节只写日志，不直接暴露给 agent
-> completed / truncated / timeout 后 supervisor 汇总日志
```

agent 可见的正式工具：

```text
stardew_action(action: str)
stardew_observe()
```

动作协议没有变化，`action` 参数仍然是原始 Stardew action 字符串：

```text
stardew_action(action="move(1, 0)")
stardew_action(action="use(\"down\")")
```

agent 不需要输出：

```text
ACTION: move(1, 0)
```

也不需要调用 curl、exec、`/benchmark/start` 或 `/benchmark/execute`。`/benchmark/execute` 是 `stardew_action` 内部使用的底层 HTTP API，不是给 agent 暴露的新动作形式。

动作是参数化的，不是只能照抄示例：

```text
move(x, y)                 # 相对移动，x/y 为整数；工具操作时建议优先用 -1/0/1 的小步
use("up"|"right"|"down"|"left")
interact("up"|"right"|"down"|"left")
choose_item(slot_index)    # 0-35，根据 inventory 选择工具/物品槽位
attach_item(slot_index)    # 0-35
unattach_item()
craft("Chest")
menu("open", "map")
menu("close", "current_menu")
choose_option(option_index, quantity, "in"|"out")
```

### 9.1 启动完整 benchmark run

确保 Windows bridge 已启动后，在 WSL/PhyAgentOS 环境运行：

```bash
micromamba activate phyagentos
paos stardew benchmark farming_lite 0 --max-steps 30 --bridge-url http://127.0.0.1:8765
```

默认会写入一个 run 目录：

```text
~/.PhyAgentOS/workspace/stardew_benchmark_runs/<task>_<id>_<timestamp>/
```

目录内包含：

```text
initial.json        # benchmark/start 返回，含 evaluator 初始状态，仅日志
agent_prompt.txt    # 发给正常 paos agent 的任务提示
agent_stdout.txt
agent_stderr.txt
tool_calls.jsonl    # 每次 stardew_action/stardew_observe 的完整日志
final_status.json   # benchmark/status 或 stop 返回
summary.json
summary.md
```

注意：`tool_calls.jsonl` 和 summary 中会记录 evaluator 细节；但 tool result 返回给 agent 的内容只包含 observation、done/truncated 停止信号和简短 instruction，避免把 evaluator/quantity/target 作为答案泄露给模型。

也可以显式使用 Python 模块入口：

```bash
python -m PhyAgentOS.cli.commands stardew benchmark farming_lite 0 --max-steps 30
```

运行时会输出：

```text
Stardew benchmark task=farming_lite[0] bridge=http://127.0.0.1:8765 max_steps=30 mode=track-a
step=0/30 completed=False truncated=False quantity=0 action=start
...
Result: completed steps=... quantity=...
```

### 9.2 可选 task

```bash
paos stardew benchmark farming_lite 0
paos stardew benchmark exploration_lite 0
paos stardew benchmark social_lite 0
paos stardew benchmark crafting_lite 0
paos stardew benchmark combat_lite 0
```

`task_id` 是 yaml 顺序中的 case 下标，从 0 开始。

### 9.3 Bridge 内部做了什么

```text
load_task(task_name, task_id)
-> task.init_task(InitTaskProxy(stardojo_port))
-> 加载 bundled save
-> 执行 yaml init_commands
-> observe raw obs
-> task.evaluate(raw_obs, task_proxy)
-> 返回 compact obs + benchmark 状态
```

Agent 看到的是 compact obs；StarDojo evaluator 使用的是 raw obs，所以可以读取 `Progression`、`farm`、`surroundingsdata`、`CurrentMenuData`、`callbackdata` 等完整字段。

### 9.4 底层 API 调试

如果只想检查 bridge，不启动 OS runner，可以手动 curl：

```bash
curl --noproxy '*' -X POST http://127.0.0.1:8765/benchmark/start \
  -H "Content-Type: application/json" \
  -d '{"task_name":"farming_lite","task_id":0,"max_steps":30}'

curl --noproxy '*' -X POST http://127.0.0.1:8765/benchmark/execute \
  -H "Content-Type: application/json" \
  -d '{"action":"move(1, 0)"}'

curl --noproxy '*' http://127.0.0.1:8765/benchmark/status
curl --noproxy '*' -X POST http://127.0.0.1:8765/benchmark/stop
```

第一版目标是验证：

```text
StarDojo benchmark task
+ normal PhyAgentOS Track A paos agent
+ formal stardew_action tool
+ Stardew bridge action
+ StarDojo evaluator
```

这条链路能闭环。

### 9.5 Benchmark 代码结构

这一版的 benchmark 结构分成五层：

```text
paos stardew benchmark
  -> Benchmark Supervisor
  -> normal paos agent / Track A AgentLoop
  -> stardew_action 正式工具
  -> bridge /benchmark/execute
  -> StarDojo evaluator
```

对应代码位置：

| 层级 | 文件 | 职责 |
|------|------|------|
| Benchmark Supervisor | `PhyAgentOS/cli/stardew_commands.py` | 初始化 benchmark case，启动正常 `paos agent`，等待结束并整理日志 |
| 正式 Track A Tool | `runtime/adapters/stardewvalley/tools.py` | 注册 `stardew_action` / `stardew_observe`，供正常 AgentLoop tool-calling |
| AgentLoop 注册点 | `agent/loop.py` | 根据环境变量 `PHYAGENTOS_STARDEW_ENABLED=1` 条件注册 Stardew tools |
| Bridge HTTP API | `runtime/adapters/stardewvalley/bridge/bridge_server.py` | 暴露 `/benchmark/start`、`/benchmark/execute`、`/benchmark/status`、`/benchmark/stop` |
| Benchmark Runtime | `runtime/adapters/stardewvalley/bridge/benchmark_runtime.py` | 管理 active session，执行动作后调用 StarDojo evaluator |
| StarDojo Task | `runtime/adapters/stardewvalley/stardojo/env/tasks/` | 原 benchmark task、yaml、evaluator 逻辑 |

关键边界：

```text
stardew_commands.py 不直接创建 AgentLoop
stardew_commands.py 不直接调用 LLM provider
stardew_commands.py 只启动正常 paos agent 子进程
stardew_action 是 agent 唯一需要调用的动作工具
bridge 和 evaluator 对 agent 保持隐藏
```

### 9.6 Benchmark 日志结构

每次运行默认创建一个目录：

```text
~/.PhyAgentOS/workspace/stardew_benchmark_runs/<task>_<id>_<timestamp>/
```

目录内容：

| 文件 | 说明 |
|------|------|
| `initial.json` | `/benchmark/start` 的完整返回，用于复盘初始化状态 |
| `agent_prompt.txt` | supervisor 发给正常 `paos agent` 的任务提示 |
| `agent_stdout.txt` | `paos agent` 标准输出 |
| `agent_stderr.txt` | `paos agent` 标准错误 |
| `tool_calls.jsonl` | 每次 `stardew_action` / `stardew_observe` 的完整记录 |
| `final_status.json` | `/benchmark/status` 或 `/benchmark/stop` 的最终状态 |
| `summary.json` | 汇总后的结构化结果 |
| `summary.md` | 便于人工阅读的结果摘要 |

`tool_calls.jsonl` 每行是一条 JSON，记录完整 bridge payload，因此包含 evaluator 细节，主要用于离线分析和复盘。

### 9.7 Agent 可见信息与隐藏评测信息

为了避免 benchmark 数据泄露，agent 不能直接看到 evaluator 细节。

agent 可见：

```json
{
  "ok": true,
  "action": "move(1, 0)",
  "obs": {},
  "done": false,
  "truncated": false,
  "instruction": "Choose the next single Stardew action from the new observation."
}
```

agent 不直接可见：

```text
benchmark.eval
quantity
target_quantity
evaluator
difficulty
完整 benchmark status
```

这些隐藏字段只写入日志：

```text
initial.json
tool_calls.jsonl
final_status.json
summary.json
```

这个边界的目的：

```text
agent 根据 observation 和任务描述做决策
evaluator 负责外部评测
supervisor 负责停止和汇总
避免把评测答案或进度信号直接喂给模型
```

---

## 十、OS 文件清单

| 文件 | 说明 |
|------|------|
| `runtime/adapters/stardewvalley/bridge/action_parser.py` | 安全 action parser |
| `runtime/adapters/stardewvalley/bridge/obs_compact.py` | compact observation + JSON-safe 转换 |
| `runtime/adapters/stardewvalley/bridge/stardew_runtime.py` | StarDojo runtime wrapper |
| `runtime/adapters/stardewvalley/bridge/bridge_server.py` | HTTP bridge API |
| `runtime/adapters/stardewvalley/target_adapter.py` | PhyAgentOS target adapter |
| `runtime/adapters/stardewvalley/stardojo/` | 内置 StarDojo 代码和 Mod |
| `runtime/adapters/factory.py` | 注册 `stardewvalley_adapter` |
| `pyproject.toml` | include 内置 StarDojo 资源 |
| `runtime/adapters/stardewvalley/tests/` | bridge 单元测试 |

---

## 十一、踩坑记录

| # | 问题 | 原因 | 修复 |
|---|------|------|------|
| 1 | WSL curl 超时，显示走 `http_proxy` | 请求被代理劫持 | 加 `curl --noproxy '*' ...` |
| 2 | `/health` 通但 `/observe` 卡住 | bridge 正常，SMAPI/StarDojo 未返回 | 检查游戏是否进存档、Mod 是否加载、10783 是否监听 |
| 3 | `/execute` 返回 `Skill not allowed` | action 不在白名单 | 只用第七节动作 |
| 4 | `use(down)` 失败 | 字符串未加引号 | 写 `use("down")` |
| 5 | 地图打开但 `current_menu` 是 `No Menu` | StarDojo 结构化 UI 识别限制 | 结合实际画面或 `latest_image_url` 判断 |
| 6 | WSL 访问 Windows IP 被拒绝 | bridge 未监听外部地址或防火墙限制 | bridge 用 `--host 0.0.0.0`，本机优先测 `127.0.0.1` |
| 7 | `latest_image_url` 为 null | 还没有可用截图 | 先调用 `/observe`，确认 StarDojo 生成截图 |

---

## 十二、复现检查清单

按顺序确认：

```text
1. Windows 已安装 Stardew Valley。
2. Windows 已安装 SMAPI。
3. StardojoMod 已放入 Mods 目录。
4. Windows 已创建 stardojo micromamba 环境。
5. Stardew Valley 通过 StardewModdingAPI.exe 启动。
6. SMAPI 控制台显示 StardojoMod 已加载。
7. 游戏已进入存档。
8. Stardew bridge 已启动，监听 0.0.0.0:8765。
9. Windows curl /health 返回 ok=true。
10. WSL curl --noproxy '*' /health 返回 ok=true。
11. /observe 能返回 obs。
12. /images/latest 能下载截图。
13. /execute move(1, 0) 后游戏角色移动。
14. PhyAgentOS config.json 模型配置可用。
15. paos agent -m "你好" 能正常回复。
16. paos stardew benchmark farming_lite 0 能启动完整 benchmark run。
```

---

## 十三、已知限制

| 限制 | 说明 |
|------|------|
| 非完整 Minecraft pipeline | 目前不通过 `SESSIONS.md + WatchdogSupervisor + SkillRuntime` 自动执行 |
| 无自动多模态注入 | obs 中有 `latest_image_url`，但不会自动进入 LLM vision 输入 |
| 每次只执行一个基础动作 | 多步任务由 Agent observe/execute 循环完成 |
| 菜单识别不完整 | `current_menu` 对部分 UI 可能不准 |
| 依赖游戏窗口状态 | 游戏必须已进入存档，SMAPI Mod 必须保持运行 |
| Windows 本地服务 | bridge 通常运行在 Windows；WSL/Linux 通过 HTTP 访问 |
