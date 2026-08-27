# PhyAgentOS 集成开发指南

[English](README_en.md) · [文档索引](../README.md)

> 版本：0.2.3

## 1. 选择接入点

| 能力 | 接入点 |
|:-----|:-------|
| 机器人读取或计算 | Gateway Query ToolSpec + ToolEndpoint operation |
| 机器人物理效果 | Gateway Action ToolSpec + ToolEndpoint operation |
| 有状态能力生命周期 | Gateway Session ToolSpec + ToolEndpoint operation |
| Dora nodes 与部署资产 | manifest v2 Skill Bundle 与锁定 Node artifacts |
| 工作流说明 | 由 SkillsLoader 发现的 `SKILL.md` |
| 用户任务成功 | 通用 `TaskVerificationContract` 与 AgentTask finalize |
| 新模型 Provider | 现有 provider registry/configuration |
| 非机器人 Agent 能力 | 现有 Agent ToolRegistry 或动态 MCP |

不要把 Agent 代码直接连接到机器人 SDK、Dora node、仿真器，或统一 Tool API 之外的旧式
Gateway Session/Policy route。

## 2. 定义 ToolSpec

每个 ToolSpec 包含稳定 `tool_id`、implementation/endpoint binding、operation、
`semantics: query|action|session`、description、严格 input/output JSON schema、readiness，以及空间
输入所需 robot frame profile。

```yaml
tool_id: motion.resolve_relative_pose
implementation_id: motion.integration
endpoint_id: motion.relative_pose
operation: resolve
semantics: query
description: Resolve a relative end-effector delta into an absolute target pose.
input_schema:
  type: object
  additionalProperties: false
  required: [translation_frame, translation_m]
  properties:
    translation_frame: {enum: [tcp, base]}
    translation_m:
      type: object
      additionalProperties: false
      required: [x, y, z]
      properties:
        x: {type: number}
        y: {type: number}
        z: {type: number}
output_schema:
  type: object
robot_frame_profile:
  base_frame: arm_base
  tool_frame: tcp
```

同步读取或不产生机器人效果的确定性解析使用 Query；有界物理效果使用 Action；显式有所有权
的有状态生命周期使用 Session。在执行方
定义 Endpoint operation `max_concurrency`，PAOS 不创建跨 Tool lease。

## 3. 实现 Query、Action 与 Session 行为

Query 从 ToolSpec 解析并调用：

```text
POST /tools/{endpoint_id}/{operation}:invoke → HTTP 200
```

Action admission 使用：

```text
POST /tools/{tool_id}:invoke → HTTP 202 + invocation_id + attempt_id
GET  /invocations/{invocation_id}
GET  /invocations/{invocation_id}/result
POST /invocations/{invocation_id}/cancel
```

Session admission 使用同一 `POST /tools/{tool_id}:invoke` 契约，通过通用 invocation routes
核对，并以 `POST /invocations/{invocation_id}/stop` 停止。必须声明 task-owned、shared 或
runtime-owned；一个 owner 不得停止另一个 owner 的 Session。

Action status/result 必须暴露明确生命周期；result pending 时可返回 HTTP 202。Cancel accepted
只表示控制处理。无法恢复执行事实时应返回显式 unknown，不能伪造 cancelled 或 success。

Input/output 必须是有限 JSON 并满足 ToolSpec。空间 Tool 必须说明 frame、unit、tolerance 与
orientation behavior，避免 Agent 无法通过 `forge_tool_context` 检查的隐藏默认值。

## 4. 构建 manifest v2 Skill Bundle

已安装 Skill Bundle 包含：

```text
<skill>/
├── skill.yaml
├── SKILL.md
├── profiles/<profile>/dataflow.yaml
├── profiles/<profile>/...
└── assets/...
```

最小 manifest 结构：

```yaml
manifest_version: 2
name: example-skill
version: "1.0.0"
description: Example robot workflow.
skill_document: SKILL.md
gateway_url: http://127.0.0.1:19002
required_tools: [example.query, example.action]
profiles:
  sim:
    dataflow: profiles/sim/dataflow.yaml
    required_binaries: [gateway, example_node]
    required_assets: [assets/scene.xml]
    required_environment: []
    environment: {}
artifacts:
  resolver: registry
  nodes:
    gateway:
      artifact_id: gateway-1.0.0-linux-x86_64
      version: "1.0.0"
      platform: linux
      arch: x86_64
      artifact_type: executable_tar_gz
      entrypoint: gateway
      sha256: <64-character-sha256>
```

所有路径必须相对并包含在 Bundle 内。每个 Node archive 具有 lock 指定的 SHA-256，并且只包含
一个 lock 指定文件名的根目录 executable；installer 在 receipt 中另行记录解包后 binary hash。
Bundle archive inventory 需要覆盖每个文件及 SHA-256；links、路径穿越、冲突、过度展开和未列出
内容会被拒绝。

## 5. 发布 artifacts

Resource Registry 或 schema v3 静态 index 必须提供 artifact identity、URL、精确 size 与
SHA-256。Node metadata 还提供 Skill lock 要求的 identity 字段。相同 artifact
identity 下不能发布可变内容。

使用与用户一致的公开命令测试安装：

```bash
python scripts/package_skill.py /path/to/example-skill --output-dir /tmp/packages
paos skill install example-skill --version 1.0.0
paos forge-node verify example-skill gateway
paos skill inspect example-skill
```

Installer 先 staging、校验，再原子替换，失败则 rollback。不得要求调用方关闭摘要校验。

## 6. 设计 Dora profile

Dataflow 为每个 Node 定义明确 inputs/outputs，并使用 Gateway profile 声明的 Tool request/
response ports。必需 executable 从不可变 Runtime environment 解析；assets 保留在 Skill Bundle
中并使用可重定位路径。

RuntimeManager 创建确定 flow name，校验 Dora 与必需文件，启动 flow，再等待 Gateway
`/tools` 与全部 required Tool context。Manifest URL 已有 Gateway 监听时不会静默接管。

Tool API 作为物理执行面时，应在 profile 禁用 Gateway Agent API：

```yaml
agent:
  enabled: false
tools:
  enabled: true
```

## 7. 编写工作流说明

`SKILL.md` 应说明何时激活、检查哪些 context、Query → Action/Session 顺序、task binding、
ownership、终态核对、
verification checkpoint 与安全恢复规则。不得嵌入 secret、Registry URL、任务特定坐标或绕过
Gateway/verification 的指令。

验证型工作流应在本轮激活 primary Skill，再由 activation 创建一个 AgentTask，把全部相关
Query/Action/Session 绑定到同一 task，全部 task-owned 执行终结后 finalize，并只在 recovery
verdict 允许时追加 PlanRevision。

## 8. Evidence 与 verification

机器人能力接入应暴露 Tool execution facts，而不是编写 action-specific verifier code。PAOS 在
AgentTask finalize 时采集配置的 image/state source 并应用通用 verification contract。
Tool output schema 应包含有用的终态 result semantics、final state/error 和相关 tolerance。

未来若引入 authoritative evidence，应显式升级 evidence contract；不能用约定把 best-effort
WebSocket association 提升为权威。

## 9. Fake Gateway 与 conformance 测试

进入真机或仿真前，使用 mock HTTP transport 测试：

- Tool list/spec/context 与 Query binding resolution；
- activation candidate 复核以及 ToolSpec/Runtime 漂移拒绝；
- Action HTTP 202 admission 及 invocation/attempt identity；
- Session admission、ownership、status/result 与 stop；
- pending status/result 与已知终态；
- cancel requested/accepted 不产生虚假停止；
- timeout/unknown 不盲目重试；
- endpoint concurrency rejection；
- 诊断 Query 与绑定调用经过相同 routes；
- AgentTask 单活动限制、revisions、evidence 与聚合 verification；
- archive traversal/link/collision/digest 攻击与事务 rollback；
- Runtime start/status/log/stop 与 availability 传播。

随后完成模拟工作流。真实机器人或 MuJoCo 验收必须记录确切 Bundle、node digests、profile 与
环境。

## 10. 接入验收清单

- [ ] Tool semantics 与 schema 明确、严格；
- [ ] Frame、unit、tolerance 与 readiness 可检查；
- [ ] Gateway operation 负责 `max_concurrency`；
- [ ] Query/Action/Session 使用文档 HTTP 契约；
- [ ] Skill/Runtime/ToolSpec binding 被冻结，并在每次受治理执行前复核；
- [ ] Invocation/attempt ID 与 PAOS task ID 分离；
- [ ] Cancel、stop、timeout、unknown 不推断物理停止，也不触发盲目 POST 重试；
- [ ] Bundle/Node artifacts 有不可变 size/digest metadata；
- [ ] Runtime profile 从干净环境启动并使全部 Tool context ready；
- [ ] Tool-only profile 禁用 Gateway Agent API；
- [ ] 通用 Agent tools、verification、experience、evolution 不需要能力专用分支。

## 后续阅读

- [开发者手册](../zh/03-developer-manual.md)
- [通信架构](COMMUNICATION.md)
- [Forge Tool API 契约](../forge/README_zh.md)
