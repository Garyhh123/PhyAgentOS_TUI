# PhyAgentOS 开发者手册

> 文档版本：0.2.1。本文面向 PAOS、Forge Gateway、Evidence、Verifier、Agent 工具与经验演化开发者。

## 1. 开发原则

涉及具身执行的改动必须保持以下不变量：

1. Forge Gateway 是唯一机器人执行入口。
2. Gateway terminal 是执行事实；任务成功由 verification policy 决定。
3. session/command ID 只由 PAOS 生成，调用方不能指定或复用。
4. 已记录 dispatch attempt 的 session 永不自动重复 POST。
5. Gateway session、command、request、action、command identity 和 policy identity 必须匹配。
6. Execution Record 写入后不可被 Verifier、review 或 retention 覆盖。
7. Evidence 必须保留真实来源、sequence、source time（若有）和 PAOS received time；不制造权威关联。
8. Verifier prompt、公共 Verdict 和 Recovery Request 与具体 `action_type` 无关。
9. parent `replanned` 与 child 创建必须在一个 SQLite 事务中完成。
10. 修改执行、证据、验证、恢复或持久化时必须覆盖失败路径和重启路径。
11. 经验按 root lineage 只计一次，保存去敏工作流结构而不是原始工具数据，且不进入 Forge 关键路径。
12. 演化必须 fail-open，不改写 operator 安全文件，只修改通过校验的 workspace Skill managed block 或生成的 Lesson 投影。

## 2. 模块地图

| 领域 | 路径 | 责任 |
|:-----|:-----|:-----|
| Agent 编排接入 | `PhyAgentOS/agent/loop.py` | 注册 Forge tools、注入 capability 摘要、处理 system event |
| Agent tools | `PhyAgentOS/agent/tools/forge.py` | JSON Schema、调用上下文与 Orchestrator facade |
| 公共契约 | `PhyAgentOS/verification/contracts.py` | Task、Session、Execution、Evidence、Verdict、Recovery 模型与状态机 |
| Verification request | `PhyAgentOS/verification/request_builder.py` | 解析 Bundle、验证 digest/窗口/要求、构造多模态请求 |
| Verification engine | `PhyAgentOS/verification/engine.py` | 无状态模型调用与 timeout |
| Verification service | `PhyAgentOS/verification/service.py` | 独立进程、readiness、鉴权和严格 JSON 输出 |
| Verifier facade | `PhyAgentOS/agent/session_verifier.py` | budget、attempt、retention、可选旧版 Lesson 写入与 review |
| Skill 激活 | `PhyAgentOS/agent/experience/activation.py` | turn 级 primary/supporting 绑定、trace 字段名与 scoped Lesson 检索 |
| 经验契约 | `PhyAgentOS/agent/experience/contracts.py` | Outcome、Episode、Assessment、Observation、Cluster、Lesson 与 Candidate 模型 |
| Outcome adapter | `PhyAgentOS/agent/experience/source.py` | 通用 `TaskOutcomeSource` 与 Forge root-lineage envelope |
| 经验协调器/存储 | `PhyAgentOS/agent/experience/coordinator.py`、`store.py` | 异步 job、root 幂等、SQLite WAL 账本与重启恢复 |
| 反思与演化 | `PhyAgentOS/agent/experience/analyzer.py`、`evolution.py` | 结构化模型调用、Lesson 生命周期、Skill 校验/晋升/回滚 |
| Gateway client | `PhyAgentOS/forge/client.py` | `httpx.AsyncClient` 的 Agent API 封装 |
| Observation | `PhyAgentOS/forge/observation.py` | 异步 WebSocket、多 source 最新帧缓存与校验 |
| Evidence writer | `PhyAgentOS/forge/evidence.py` | 安全路径、原子写入、SHA-256、snapshot 与 Bundle |
| Adapter | `PhyAgentOS/forge/adapter.py` | 单 action 执行、identity、poll、timeout、cancel 和映射 |
| Store | `PhyAgentOS/forge/store.py` | SQLite WAL、事务、状态、事件和原子 replan |
| Orchestrator | `PhyAgentOS/forge/orchestrator.py` | 异步任务、mode、restart、recovery 和通知 |
| 配置 | `PhyAgentOS/config/schema.py` | Forge、Evidence、Verification、Embodiment Schema |

## 3. 公共模型

### 3.1 `ForgeTaskRequest`

```python
ForgeTaskRequest(
    task_description="Place the red object in the tray",
    action_type="<gateway-advertised-action>",
    inputs={...},
    verification=TaskVerificationContract(...),
    execution_timeout_s=300.0,
)
```

`inputs` 必须是有限 JSON 值；NaN、Infinity、不可序列化对象和空 `task_description`/`action_type` 被拒绝。

### 3.2 `TaskVerificationContract`

`mode != off` 时，goal 与至少一个 criterion 必填。criteria 和 constraints 中不能有空字符串。Evidence policy 默认要求 `rgb_image`，并允许任务覆盖 source；source 为空时使用 target-level Forge 配置或 readiness 发现。

### 3.3 `ExecutionRecord`

模型设置 `frozen=True`。它包含：

- PAOS/Gateway session ID 与 command ID；
- Gateway API/instance；
- action type 与 policy ID；
- normalized execution status；
- capability 声明的通用 `result_semantics` 和 `completion`；
- Gateway timeline、outputs 与 error。

不得在该模型中写入 task verdict，也不得因为 Verifier 不认可结果而把 Gateway `succeeded` 改为 `failed`。

### 3.4 `EvidenceBundle`

每个 artifact 包含 phase、kind、source ID、sequence、captured/received time、media type、byte size、SHA-256、安全 workspace-relative URI、retention 状态。`EvidenceQuality` 单独记录 completeness、association、missing requirements、stale artifacts 和 errors。

### 3.5 `VerificationVerdict`

Verifier 必须为输入的每条 success criterion 返回且只返回一个 `CriterionVerdict`，并逐字复制 criterion。`success` 要求全部 `satisfied`；`failure`/`replan_required` 至少有一项未满足或 unknown；`replan_required` 还必须提供动作无关的 `recovery_context`。

### 3.6 经验契约

经验子系统具有独立版本化边界：

| 模型 | 作用 |
|:-----|:-----|
| `TaskOutcomeEnvelope` | Provider 无关的语义结果、criterion 状态、lineage attempts 与不透明记录/证据引用 |
| `TaskEpisode` | 一个去敏 root task，加 Skill activations 与 workflow trace |
| `ExperienceAssessment` | 包含复用判定、Skill proposal、failure observations、反证和冲突的结构化反思 |
| `LessonEligibility` | `related | unrelated | uncertain` 归因、有限 reason enum 与置信度 |
| `FailureObservation` | 不包含具体答案或原始任务值的规范化工作流失败模式 |
| `LessonCluster` | 同 Skill、同 workflow、同 canonical pattern 的支持和合成状态 |
| `ScopedLesson` | 适用/不适用边界、失败模式、建议、来源支持与生命周期状态 |
| `SkillCandidate` | create/update proposal、独立支持、blocker、revision 与晋升状态 |

这些契约拒绝额外字段。持久化 workflow trace 只包含工具名和输入字段名；endpoint、凭据、绝对路径、command ID、原始输出与 evidence locator 会被删除或替换成不透明引用。Lineage session ID 只作为内部不可变 record reference 保留，禁止进入生成的 Lesson/Skill 内容。

## 4. 状态机与事务

允许转换定义在 `ALLOWED_FORGE_TRANSITIONS`。Store 的所有 update 会先加载模型、执行 mutation、验证转换、更新时间、写 JSON、追加 event，再提交事务。

SQLite 表：

```text
forge_sessions
  session_id PRIMARY KEY
  command_id UNIQUE
  root_session_id
  parent_session_id UNIQUE
  status
  record_json
  created_at / updated_at

forge_events
  event_id PRIMARY KEY
  session_id FOREIGN KEY
  event_type
  created_at
  payload_json
```

`BEGIN IMMEDIATE` 用于任务创建与 replan，确保多个 PAOS Store 实例并发提交时仍只有一个 non-terminal lineage。

经验状态独立存放在 `.paos/evolution/experience.sqlite3`。表包括 task binding、root 唯一的 episode/job、scoped Lesson、failure observation、Lesson cluster、唯一 `(cluster_id, root_task_id)` 支持、cluster job、Skill candidate、event 与 migration metadata。WAL 和 `BEGIN IMMEDIATE` 保护写入；进程启动时会把中断的 running job 恢复为 `pending`。该数据库不参与 Forge 状态转换。

## 5. Gateway 启动契约

`ForgeAdapter.validate_capabilities()` 要求：

```json
{
  "api_version": "paos-forge-gateway-mvp-plus.v1",
  "supports": {
    "sessions": true,
    "command_id": true,
    "runtime_context": true,
    "serial_actions_only": true
  },
  "actions": {
    "<action_type>": {
      "policy_id": "...",
      "command": "...",
      "result_semantics": "command_completed",
      "completion": {},
      "required_parameters": [],
      "input_mapping": {}
    }
  }
}
```

Capability 中的 action metadata 用于 Planner 选择与 Execution Record，不用于选择 verifier 分支。

## 6. Adapter 执行协议

全新任务的顺序不可交换：

1. 检查 action capability。
2. 非 `off` 时启动 images/state collectors。
3. 等待 required sources，并原子写 before snapshot。
4. Orchestrator 持久化 `dispatching`/dispatch attempt。
5. POST `/agent/sessions`。
6. 校验 create response 的 session/command/action identity。
7. 轮询 `/agent/sessions/{session_id}`。
8. 只接受 `succeeded | failed | cancelled`；timeout 时请求 cancel。
9. 观察终态后等待更高 image sequence，再写 after snapshot。
10. 写 immutable Execution Record 和 Evidence Bundle。

Gateway payload 为：

```json
{
  "session_id": "forge_<generated>",
  "command_id": "command_<generated>",
  "action_type": "...",
  "instruction": "...",
  "source": "paos-agent",
  "inputs": {}
}
```

执行终态必须同时满足：

```text
session.session_id == requested session_id
command.command_id == requested command_id
command.session_id == requested session_id
command.request_id == requested command_id
session.action_type == requested action_type
command.action_type/policy_id/command == advertised capability identity
session.status == command.status in succeeded|failed|cancelled
```

## 7. Observation 与 Evidence

Collector 为每个 required image source 只保留最高 sequence 的合法帧；重复或乱序帧不会替换最新帧。连接断开后会重连，最近错误保留有界列表。

当前接受：

- `image/jpeg`/`image/jpg`；
- `image/png`；
- `image/webp`；
- JSON robot state。

除了 Base64 长度与实体大小限制，还检查 magic bytes。Artifact filename 包含安全化 source label、source digest 和 sequence，防止不同 source 安全化后发生路径冲突。所有 URI 必须是 workspace-relative 且不能包含 `..`。

`VerificationRequestBuilder` 在调用模型前再次检查：

- Bundle 与 session/command identity；
- completeness 与 minimum association；
- capture window 顺序；
- required kind/source 在 before/after 均存在；
- entity retained、存在、大小与 SHA-256 一致；
- image media type 与实体相符；
- evidence ID 唯一。

## 8. Verification Service

`ForgeTaskVerifier` 启动一个独立 Python 子进程。服务只监听配置 host/port，使用 per-process token 的 `X-PAOS-Admin-Token`，提供：

```text
GET  /healthz
POST /v1/verify-task
```

request version 为 `forge_verification_request_v1`。启动 readiness 固定有界，模型调用受 `timeoutS` 和 `maxVerifierCallsPerRun` 限制。

Prompt 只包含：

- task goal、success criteria、constraints；
- immutable Execution Record；
- Evidence Bundle 与实体；
- root lineage history；
- 启用 evolution 时，root task 显式 Skill activation 冻结的 active scoped Lessons；
- 其他情况下存在的旧版/人工根目录 Lessons；
- 合法 evidence IDs。

Scoped Lesson 是不可信、非权威的工作流建议。Service prompt 禁止用它确定 criterion 状态、替代任务契约或证据，以及填充 evidence reference。Evolution 模式的自动验证与 review 都不读取根目录 `LESSONS.md`；未绑定 Skill 的任务收到空 Lesson 集合。非法服务输出会被规范为 `inconclusive`，随后公共模型和 exact-criteria validator 继续校验。`audit` 记录错误；`enforce`/`recovery` fail closed。Verdict 的 `lesson` 字段只作为反思输入；启用 evolution 时，Verifier 不再把它直接追加到根目录 `LESSONS.md`。

## 9. Recovery

Verifier 只能建议 `replan_required`，不能输出 action type、策略参数或 Gateway input。Orchestrator 从 verdict 构造 `RecoveryRequest`，通过 `InboundMessage(channel="system")` 唤醒原 Agent session。

Planner 调用 `create_replanned_forge_session` 时：

- parent 必须仍为 `awaiting_replan`；
- deadline 未过期；
- replan budget 未耗尽；
- child 继承 verification contract、root lineage、来源路由与 source；
- Planner 重新提供 task description、action type、inputs；
- PAOS 生成新的 session/command ID；
- parent terminal 与 child create 原子提交；重复调用返回已有 child。

## 10. Agent 任务经验与 Skill 自进化

### 10.1 激活与归因

`activate_skill` 只解析 `SkillsLoader` 注册的精确 hyphen-case 名称，遵循 workspace 优先于 built-in，并拒绝 unavailable Skill 和任意路径。一个 turn 可激活一个 primary 和多个 supporting Skill。返回值包含完整 Skill、activation record/digest 与排序后的 active Lesson。只有 primary 可自动更新；supporting Skill 可接收失败归因。

AgentLoop 在 turn 内记录工具顺序和参数字段名。`forge_execute_task` 接受新 root session 后，将 activation snapshot 绑定到 root ID。直接读取 `SKILL.md` 不算激活；无激活任务保持 unbound，系统不会事后猜测关联。

### 10.2 Outcome 捕获与反思 job

`ForgeTaskOutcomeSource` 把完整 root lineage 转换为去敏 `TaskOutcomeEnvelope`。自动终结 system event 对同一 root 最多创建一个 episode/job；recovery child、重复 event、进程 replay 与人工 review 都不能增加独立支持。

只有语义 `success`、`failure`、`replan_required` 可学习。成功必须具有非空 criterion statuses 且全部为 `satisfied`。恢复后成功属于 `mixed`：既可支持最终成功工作流，也保留规范化失败尝试。`off`、`inconclusive`、非法/服务错误和 review-only 结果被排除。

Coordinator 先持久化再调度 `asyncio` 反思，并按已存 job 策略重试。其调用计数与 `maxVerifierCallsPerRun` 分离；evolution budget 耗尽只延后 job，不改变任务结果。

### 10.3 Lesson 聚类与生命周期

反思模型为每个 failed/replanned 工作流模式输出 `LessonEligibility`。只有 `decision=related` 且 `reason=workflow_related` 继续；`task_unsatisfiable`、`verifier_limit`、`evidence_limit`、`external_or_infrastructure`、`user_constraint` 和 `unknown` 只形成诊断事件。

相关失败转换为规范化 `FailureObservation`。模型在语义等价时选择同 Skill/同 workflow 的现有 cluster，否则提出稳定 `pattern_key`；首期不使用 embedding 或向量数据库。SQLite 对每个 cluster 的 root 只计一次；低于 `minLessonEpisodes` 时保持 `collecting`。

达到门槛后，Lesson 合成只接收规范化 observations，不接收原始 inputs。静态校验拒绝凭据、endpoint、路径、action/command/session ID、Action Manifest 内容、绕过指令、prompt injection、固定坐标/数值/选项与答案式表达。第二层结构化模型校验必须得到 `reusable=true`、`contains_specific_answer=false`、空 `unsupported_literals` 且置信度至少 `0.8`；否则 cluster 变为 `blocked`，永不注入。

active `ScopedLesson` 只能被同 Skill/workflow 作用域内的 active replacement supersede。独立成功反证可使其 retired 并重新打开 cluster。`references/LESSONS.md` 是 active/历史 Lesson 及 collecting/blocked cluster 的原子人类可读投影，SQLite 账本才是事实源。`activate_skill` 最多返回 `maxLessonsPerSkill` 条 active 且作用域匹配的 Lesson。

首次启动时，根目录 `LESSONS.md` 条目被导入为 inactive unbound legacy record。已有的 pre-cluster active Lesson 会先降为 inactive，按已知 episode roots 形成 cluster seed，并在重新合成和验证通过后才可恢复 active。

### 10.4 Skill candidate 与晋升

可复用语义成功按 Skill 和 workflow key 创建或合并 candidate。Update proposal 必须指向已激活 primary Skill；没有 primary 时可提出不重复的新 Skill。独立 episode ID 提供支持；晋升要求达到 `minSuccessfulEpisodes`，并会被同 workflow active Lesson、反思冲突、校验错误或不安全内容阻止。

生成内容只允许 trigger、preconditions、通用 steps、verification checkpoints、recovery guidance 和 applicability boundaries，不允许 scripts/assets、endpoint、凭据、固定 Gateway action/ID、Action Manifest 副本或绕过 Forge/verification 的指令。

新 Skill 写入 `workspace/skills/<name>/SKILL.md` 且 `always: false`。更新只替换一个 `<!-- paos:learned-workflow:start -->` managed block，保留人工正文。Built-in baseline 先归档，再复制为 workspace override；built-in 文件永不修改。原子写入、结构/内容校验、workspace reload、revision archive 与 rollback 保护每次晋升。当前 turn 继续使用已激活 digest，后续 turn 才读取刷新后的 summary。

## 11. 扩展工作流

### 11.1 新增 Gateway action

action 实现与注册发生在 Forge Gateway/Runtime 仓库，而不是 PAOS：

1. 在 Gateway capabilities 中发布稳定 action identity。
2. 明确 `required_parameters`、`input_mapping`、`result_semantics` 和 `completion`。
3. 保证 create/get 返回完整且一致的 session/command identity。
4. 保证终态枚举符合契约。
5. 在 PAOS 中只增加通用 contract/fake Gateway 测试；不要添加 action-specific verifier flag。

### 11.2 新增证据 source

在 Gateway `/ws/images` 发布稳定 `id`、单调递增 `seq`、合法 `content_type` 和 Base64 数据；可选 `timestamp` 必须是真实 source time。PAOS target config 或 task evidence policy 引用 source ID。

需要新 evidence kind 时，应同时扩展公共契约、采集/写入、request builder、retention 和端到端测试，而不是在 action manifest 中塞入私有路径。

### 11.3 新增 Agent tool

只有当能力不能由七个通用 Forge tools 表达时才新增。新 tool 不得让调用者指定 session/command ID，不得直接 POST Gateway，不得绕过 Store/Orchestrator。

## 12. 错误与可观测性

稳定错误前缀用于运维分层：

| 类别 | 示例 |
|:-----|:-----|
| Gateway contract | `FORGE_GATEWAY_API_UNSUPPORTED`, `FORGE_GATEWAY_CAPABILITY_MISSING` |
| Action/correlation | `FORGE_ACTION_UNSUPPORTED`, `FORGE_EXECUTION_STATE_LOST` |
| Evidence | `FORGE_EVIDENCE_CONFIGURATION_REQUIRED`, `FORGE_EVIDENCE_UNAVAILABLE`, `VERIFICATION_EVIDENCE_UNAVAILABLE` |
| Verification | `VERIFICATION_INVALID_VERDICT`, `VERIFICATION_CALL_BUDGET_EXHAUSTED`, `VERIFICATION_SERVICE_UNAVAILABLE` |
| Recovery | `VERIFICATION_REPLAN_LIMIT_REACHED`, `VERIFICATION_REPLAN_TIMEOUT` |
| Execution | `GATEWAY_EXECUTION_TIMEOUT`, `GATEWAY_SESSION_FAILED`, `FORGE_SESSION_CANCELLED` |

SQLite event log 是编排审计源；Gateway 原始 create/last/cancel response 保存在 session record 中；公共 Artifact 提供跨进程可读事实。

Evolution 使用独立结构化 event stream，包括 episode/assessment 完成、eligibility rejected、observation/cluster support、Lesson activated/superseded/retired、candidate supported/blocked/promoted、validation rejected、budget deferred、baseline archived 与 rollback。日志只暴露 ID 和有限摘要，不记录敏感任务值。

## 13. 测试

```bash
python -m pip install -e ".[dev]"
pytest
ruff check PhyAgentOS tests
python -m compileall -q PhyAgentOS tests
```

测试应覆盖：

- model version、必填字段、非法状态/verdict/URI/digest；
- Store 并发、单活动 lineage、transition、原子 replan；
- Gateway API/support/action/identity/terminal/cancel/reset；
- 多 source、乱序、重复、陈旧帧、断线、非法媒体、超大 artifact；
- 四种 mode、缺证、Verifier 服务错误、retention 和 review 不改终态；
- restart 的 POST 前、POST 后 404、补采、验证中断与 recovery 去重；
- Agent tool 注册、system event 路由和 Forge disabled；
- repository guard，防止旧执行体系返回活动代码；
- 精确 Skill 激活、workspace 优先级、primary 唯一、supporting、availability 与路径拒绝；
- learnable outcome 分类、root/replay/recovery/review 幂等、trace 去敏、job restart 与 fail-open；
- Lesson eligibility、同模式聚类、独立 root 门槛、静态/模型抽象校验、投影、迁移、supersession 与 retirement；
- 第一/二/三次成功晋升、blocker、managed block 保护、built-in override、原子 revision archive、reload 与 rollback。

可选黑盒测试只通过 `FORGE_GATEWAY_URL` 连接运行中的 Gateway，不修改其源码或配置。

## 后续阅读

- [集成开发指南](../user_development_guide/README.md)
- [通信架构](../user_development_guide/COMMUNICATION.md)
- [Forge 接入契约](../forge/README_zh.md)
- [配置参考](04-forge-configuration-reference.md)
- [Agent 经验与 Skill 自进化](05-agent-experience-and-skill-evolution.md)
