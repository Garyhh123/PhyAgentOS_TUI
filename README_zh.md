# PhyAgentOS TUI

PhyAgentOS 的官方终端用户界面。

`phyagentos-tui` 提供基于 Textual 的本地终端工作台，用来操作一套本地
PhyAgentOS 环境。它不重新实现 Agent Runtime，而是复用 `PhyAgentOS-ai`
提供的配置、模型供应商、消息渠道、Forge Tool API、AgentTask 账本、
Evidence 记录和 Skill Runtime 状态。

这个仓库不再包含 demo 回放脚本。它的定位是可长期维护、可发布、可作为官方
仓库独立演进的 TUI 层。

## 与 Core 的关系

PhyAgentOS core 负责物理智能体运行时和执行契约：

- Agent loop、工具、记忆、Cron、Heartbeat、MCP 和渠道
- 模型供应商配置与模型路由
- Forge Tool API 客户端与 AgentTask 持久化
- Evidence 采集、Verifier、恢复流程和 Skill Runtime 状态

PhyAgentOS TUI 负责终端交互层：

- Chat 页面：和本地 Agent 直接对话
- Providers 页面：配置 API Key、API Base 和供应商默认项
- Channels 页面：查看并开关可用渠道
- Settings 页面：修改常用本地默认配置
- Forge Runtime 页面：只读查看会话、制品、存储和健康状态
- 命令面板、页面导航、状态栏和日志捕获

把这两层分开，可以让界面独立迭代，同时避免 UI 发布节奏绑定核心物理执行
运行时。

## 安装

推荐使用 Python 3.11 或 3.12。

```bash
git clone https://github.com/PhyAgentOS/PhyAgentOS-TUI.git
cd PhyAgentOS-TUI
python -m pip install -e .
```

当前开发版本依赖 PhyAgentOS core 的 `dev` 分支：

```toml
PhyAgentOS-ai @ git+https://github.com/PhyAgentOS/PhyAgentOS-core.git@dev
```

正式发布时，应该把这个分支依赖替换为匹配的 `PhyAgentOS-ai` 发布版本。

## 启动

直接启动 TUI：

```bash
paos-tui
```

也可以用模块方式启动：

```bash
python -m phyagentos_tui
```

如果 core 中已经接入了 TUI 入口，也可以通过：

```bash
paos tui
```

## 首次使用

先通过 core 初始化工作区：

```bash
paos onboard
```

然后进入 TUI：

1. 打开 `Providers`。
2. 选择需要使用的模型供应商。
3. 填入 API Key 和可选的 API Base。
4. 保存配置，并按需设为默认供应商。
5. 回到 `Chat` 页面开始使用。

TUI 读写的是 PhyAgentOS CLI 使用的同一份配置。

## 页面

| 页面 | 用途 |
|:-----|:-----|
| Chat | 通过本地消息总线与 PhyAgentOS Agent 直接对话。 |
| Providers | 配置模型供应商、API Key 和兼容中转地址。 |
| Channels | 查看并开关可用的渠道集成。 |
| Settings | 编辑供应商、模型、网关端口、主题和工具等常用默认项。 |
| Forge Runtime | 只读查看 AgentTask、Skill Runtime、Evidence、存储和健康记录，并隐藏本机隐私路径。 |

## 快捷键

| 快捷键 | 行为 |
|:-------|:-----|
| `Ctrl+K` | 打开命令面板。 |
| `Ctrl+1` 到 `Ctrl+5` | 切换主页面。 |
| `Alt+Left` / `Alt+Right` | 切换上一页或下一页。 |
| `Esc` | 返回 Chat；在 Chat 页面连续按两次退出。 |
| `Ctrl+R` | 重启本地 Gateway 服务。 |

部分页面还支持刷新、保存、搜索、复制等局部快捷键。支持帮助的页面可以按 `?`
查看页面说明。

## 开发

安装开发依赖：

```bash
python -m pip install -e ".[dev]"
```

运行质量检查：

```bash
ruff check phyagentos_tui tests
pytest
python -m compileall -q phyagentos_tui tests
```

构建发布包：

```bash
python -m pip install build
python -m build
```

## 仓库结构

```text
phyagentos_tui/
  app.py                  # Textual 应用入口和页面导航
  styles.tcss             # TUI 布局和视觉样式
  themes.py               # 主题注册
  screens/                # Chat、Providers、Channels、Settings、Runtime
  services/               # 内嵌 Gateway 生命周期集成
  widgets/                # 共享 Textual 组件
tests/                    # 冒烟测试和导入检查
```

## 兼容性

当前版本跟随 PhyAgentOS core 的 `dev` 分支。core 如果调整以下接口，需要同步
检查 TUI：

- `PhyAgentOS.config`
- `PhyAgentOS.cli.commands._make_provider`
- `PhyAgentOS.cli.commands._make_forge_components`
- `PhyAgentOS.bus`
- provider registry 和 channel registry API
- Forge AgentTask 存储结构

## 安全与隐私

Runtime 页面会尽量使用工作区相对路径或脱敏标签展示本地存储位置，不应暴露
绝对 home 路径、用户名、API Key 或模型供应商密钥。

Provider API Key 通过密码输入框填写，并通过 PhyAgentOS core 的配置写入逻辑
保存。具体密钥存储和部署控制遵循 core 的安全模型。

## 贡献

欢迎提交 Issue 和 Pull Request。TUI 的职责是查看、配置和路由 PhyAgentOS
能力，不应在 Forge Tool API 之外再定义第二套物理执行协议。

开发约定见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

MIT License。见 [LICENSE](LICENSE)。
