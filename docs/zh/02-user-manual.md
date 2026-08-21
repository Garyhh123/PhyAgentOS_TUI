# PhyAgentOS 用户手册

[English](../en/02-user-manual.md) · [文档索引](../README.md)

> 文档版本：0.2.2。

## 1. 安装与初始化

PhyAgentOS 支持 Python 3.11 和 3.12。Forge Gateway、Dora、机器人驱动、仿真资产与锁定 Node
制品在机器人 Skill 需要时独立部署。

```bash
git clone https://github.com/PhyAgentOS/PhyAgentOS.git
cd PhyAgentOS
python -m pip install -e .
paos onboard
```

开发环境：

```bash
python -m pip install -e ".[dev]"
pytest
ruff check PhyAgentOS tests
```

默认配置位于 `~/.PhyAgentOS/config.json`，默认工作区为
`~/.PhyAgentOS/workspace`。

## 2. 配置模型与 Forge

先配置一个模型 Provider；需要 Agent 调用 Gateway Tools 时再启用 Forge。配置以 camelCase
保存，也接受 snake_case。

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.PhyAgentOS/workspace",
      "model": "openrouter/openai/gpt-4o-mini",
      "provider": "openrouter"
    },
    "verification": {
      "serviceEnabled": true,
      "evidenceRetention": "failed",
      "maxReplansPerEpisode": 2
    },
    "evolution": {
      "enabled": true,
      "minSuccessfulEpisodes": 3,
      "minLessonEpisodes": 3
    }
  },
  "providers": {
    "openrouter": {"apiKey": "YOUR_API_KEY"}
  },
  "forge": {
    "enabled": true,
    "baseUrl": "http://127.0.0.1:9001",
    "apiVersion": "forge-tool-api.v1",
    "requestTimeoutS": 10,
    "pollIntervalS": 0.5,
    "executionTimeoutS": 300,
    "evidence": {
      "requiredImageSources": ["front"],
      "associationQuality": "best_effort"
    }
  },
  "resourceRegistry": {"url": ""}
}
```

活动 Skill Runtime manifest 的 `gateway_url` 优先于 `forge.baseUrl`。也可以通过
`PAOS_RESOURCE_REGISTRY_URL` 提供 Registry URL；空 URL 表示不进行隐式下载。

## 3. 安装并运行 Skill Runtime

使用已配置 Registry 或 schema v3 静态 package index：

```bash
paos skill search move-arm-by-ee
paos skill install move-arm-by-ee --version 0.2.0
# 或：paos skill install move-arm-by-ee --index /path/to/index.json

paos skill list
paos skill inspect move-arm-by-ee
paos skill start move-arm-by-ee --profile mujoco
paos skill status move-arm-by-ee
```

`install` 校验归档大小、SHA-256、内嵌文件清单、manifest v2 与锁定 Node，全部通过后才原子
替换 Skill。`start` 只启动指定 Dora profile，并检查 Gateway `/tools` 与所需 Tool context。
使用 `paos skill logs move-arm-by-ee` 查看生命周期日志，使用
`paos skill stop move-arm-by-ee` 停止。

Node 制品可以独立管理：

```bash
paos forge-node install <artifact-id>
paos forge-node verify <node-id> <artifact-id>
```

内置 `move-arm-by-ee` Skill 提供工作流文档，但运行 MuJoCo profile 仍需要匹配的 Bundle
assets 与锁定 Node 制品。

## 4. 启动 PAOS

使用已安装机器人 Skill 时，按 Dora、Skill Runtime/Gateway、Agent 的顺序启动。若 Gateway
由外部管理，只需保证 Agent 调用前已就绪。

```bash
paos status
paos agent

# 单条请求
paos agent -m "检查运动 Tool context，将夹爪向前移动 5 cm，并验证结果。"

# 长期运行消息渠道、Cron、Heartbeat 与 Agent
paos gateway
```

## 5. 检查 Tool context

调用 Tool 前使用 `forge_tool_context(tool_id)`。它返回 ToolSpec，以及实时 binding、
readiness、endpoint status 和机器人 frame 信息。Agent 必须遵循精确 input schema，不能猜测
frame 或单位约定。

内置运动工作流使用：

- Query `motion.resolve_relative_pose` 解析相对末端目标；
- Action `motion.move_pose` 启动移动；
- Action `gripper.set_opening` 设置夹爪开度。

## 6. 选择绑定或无任务执行

无任务 Query/Action 使用同一 Tool API，但不计入用户任务验证：

```text
forge_tool_query(tool_id, arguments)
forge_tool_start_action(tool_id, arguments)
```

对于用户可见的多调用任务：

1. 调用 `forge_task_create(task_description, verification)` 并保存 `task_id`；
2. 把该 `task_id` 传给所有参与任务的 Query 或 Action；
3. 对每个 Action 保存返回的 `invocation_id` 与 `attempt_id`；
4. 使用 `forge_tool_action_status` 与 `forge_tool_action_result` 核对到终态；
5. 所有绑定 Action 终结后调用 `forge_task_finalize(task_id)`。

全局最多一个非终态 AgentTask。无任务调用不占此槽位，所有执行仍按 Gateway operation 的
`max_concurrency` 竞争。

## 7. 定义验证

`audit`、`enforce` 或 `recovery` 必须提供 goal 和至少一项 success criterion：

```json
{
  "mode": "recovery",
  "goal": "夹爪相对初始位姿向前移动 5 cm。",
  "success_criteria": [
    "末端最终位姿在声明 frame 中近似向前 5 cm。",
    "机器人未报告碰撞或移动失败。"
  ],
  "constraints": ["保持末端方向不变。"],
  "evidence_policy": {
    "required_kinds": ["rgb_image"],
    "required_sources": ["front"],
    "minimum_association": "best_effort"
  }
}
```

| 模式 | 行为 |
|:-----|:-----|
| `off` | 根据绑定 Tool execution facts 派生任务结果。 |
| `audit` | 记录语义验证，同时保留执行派生结果。 |
| `enforce` | 语义验证决定成功；缺失或非法验证时 fail closed。 |
| `recovery` | 与 enforce 相同；`replan_required` 允许有预算的新 PlanRevision。 |

finalize 返回 `awaiting_replan` 时调用
`forge_task_begin_revision(task_id, reason)`，并继续使用同一 task ID。不要创建第二个任务，也
不要重试物理效果未知的 invocation。

## 8. 取消与 unknown 结果

`forge_tool_cancel_action(invocation_id)` 发出取消请求。`requested` 或 `accepted` 只确认控制
消息处理；应继续读取 status/result，直到 Gateway 报告已知终态。`unknown` 和本地 timeout
可用于任务记账终结，但不能证明物理停止。

`forge_task_cancel(task_id, reason)` 为全部非终态绑定 Action 请求取消，并将任务置为
`cancelling`。随后应核对 invocation，必要时检查现场，再显式 finalize。存在不确定 invocation
时 Runtime stop 保持门控，除非运维人员明确 force。

## 9. Experience、activation 与 evolution

注册 Skill 与工作流匹配时，在第一次工作流工具调用前使用 `activate_skill(name, role)`。
Skill 发现优先级为 workspace、已安装、内置；Runtime availability 参与激活资格判断。

Experience 记录全部 Agent tool calls，并把 AgentTask、PlanRevision、invocation 引用、验证和
显式 Skill activation 归入一个 episode。Scoped Lesson 只是建议，不能替代任务 criteria 或
evidence。Evolution fail-open，反思错误不会改变执行或验证。

## 10. 持久化与 retention

```text
<workspace>/
├── .paos/agent_tasks/tasks.sqlite3
├── .paos/evolution/experience.sqlite3
├── .paos/evolution/revisions/<skill>/
├── skills/<skill>/
└── artifacts/agent_tasks/<task_id>/
    ├── before_snapshot.json
    ├── after_snapshot.json
    ├── evidence_bundle.json
    └── evidence/
```

备份时先停止 PAOS，将 SQLite 及 WAL/SHM 文件、完整 artifact 和 Skill revision 目录一起备份。
`evidenceRetention` 控制验证后的证据保留，不删除 execution record 或 evolution 历史。

## 11. 故障排查

| 现象 | 检查项 |
|:-----|:-------|
| Tool 不存在或未就绪 | 运行 `forge_tool_context`，检查 ToolSpec、binding、Endpoint 与 Runtime profile。 |
| Skill 无法安装 | 确认 Registry/index 提供 size、SHA-256，且全部 Node lock 可解析。 |
| Skill 无法启动 | 运行 `paos skill status` 与 `logs`，检查 Dora、dataflow、assets、nodes 和 Gateway `/tools`。 |
| 已有活动任务 | 使用 `forge_task_get` 读取已知任务，完成或取消它，不要编辑 SQLite。 |
| Action result 为 pending | 使用相同 `invocation_id` 继续核对 status/result。 |
| Action result 为 unknown | 检查 Gateway、Dora 与物理现场，不要盲目重试。 |
| Verification 失败 | 检查任务 criteria、Tool records、evidence bundle 与 verifier availability。 |
| 未加载 Skill Lesson | 确认显式 activation、Runtime availability 和符合条件的 active scoped Lessons。 |

## 后续阅读

- [Forge 配置参考](04-forge-configuration-reference.md)
- [运行手册](../user_manual/README.md)
- [Forge Tool API 接入契约](../forge/README_zh.md)
