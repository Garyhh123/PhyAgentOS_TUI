# PhyAgentOS-G 文档 / Documentation

[English](#documentation-index) | [中文](#文档索引)

---

## 文档索引

PhyAgentOS-G 文档体系由四部分组成，分别面向不同读者群：

| Part | 文档 | 面向 | 内容 |
|:-----|:-----|:-----|:-----|
| 1 | [框架介绍](zh/01-framework-introduction.md) | 所有人 | 游戏智能体研究理念、Session-Centered Runtime 架构、当前进展、路线图 |
| 2 | [用户手册](zh/02-user-manual.md) | 使用者 | 快速开始、Minecraft Game Agent 配置、仿真验证、排障指南 |
| 3 | [开发者手册](zh/03-developer-manual.md) | 开发者 | API 接口、Target/Adapter/Skill 开发、代码风格、贡献规则 |
| 4 | [场景文档](scenarios/game/minecraft/zh/) | 使用者+开发者 | Minecraft 完整部署指南、使用手册、踩坑记录 |

### 阅读路径

| 你的目标 | 建议先读 |
|---------|---------|
| 了解项目是什么、能做什么 | [Part 1: 框架介绍](zh/01-framework-introduction.md) |
| 快速跑通系统 | [Part 2: 用户手册 §2.4](zh/02-user-manual.md#24-5-分钟快速开始) |
| 部署 Minecraft Game Agent | [场景文档：部署指南](scenarios/game/minecraft/zh/deployment.md) |
| 添加新 Game Target | [Part 3: 开发者手册 §3.4](zh/03-developer-manual.md#34-二次开发指南) |
| 理解 Runtime 架构全貌 | [Part 1 §1.3](zh/01-framework-introduction.md#13-技术架构) → [Part 3 §3.2](zh/03-developer-manual.md#32-架构深度解析) |

### 场景文档索引

| 场景 | 部署指南 | 使用指南 | 源码 |
|------|---------|---------|------|
| Minecraft Game Agent | [zh](scenarios/game/minecraft/zh/deployment.md) / [en](scenarios/game/minecraft/en/deployment.md) | [zh](scenarios/game/minecraft/zh/usage.md) / [en](scenarios/game/minecraft/en/usage.md) | [bridge_server.js](scenarios/game/minecraft/bridge_server.js) |

### 版本信息

- 项目版本：v0.0.3（基于 PhyAgentOS v0.1.4 重构）
- 文档版本：v2.0
- 最后更新：2026-06-11

---

## Documentation Index

The PhyAgentOS-G documentation consists of four parts targeting different audiences:

| Part | Document | Audience | Content |
|:-----|:---------|:---------|:--------|
| 1 | [Framework Introduction](en/01-framework-introduction.md) | Everyone | Game agent research philosophy, Session-Centered Runtime architecture, progress, roadmap |
| 2 | [User Manual](en/02-user-manual.md) | Users | Quick start, Minecraft Game Agent setup, simulation validation, troubleshooting |
| 3 | [Developer Manual](en/03-developer-manual.md) | Developers | API reference, Target/Adapter/Skill development, coding style, contribution |
| 4 | [Scenario Docs](scenarios/game/minecraft/en/) | Users + Devs | Complete Minecraft deployment guide, usage manual, troubleshooting |

### Reading Path

| Your Goal | Start With |
|-----------|-----------|
| Understand what the project is | [Part 1: Framework Introduction](en/01-framework-introduction.md) |
| Get the system running | [Part 2: User Manual §2.4](en/02-user-manual.md#24-5-minute-quick-start) |
| Deploy Minecraft Game Agent | [Scenario: Deployment Guide](scenarios/game/minecraft/en/deployment.md) |
| Add a new Game Target | [Part 3: Developer Manual §3.4](en/03-developer-manual.md#34-secondary-development-guide) |
| Understand the full Runtime architecture | [Part 1 §1.3](en/01-framework-introduction.md#13-technical-architecture) → [Part 3 §3.2](en/03-developer-manual.md#32-architecture-deep-dive) |

### Scenario Doc Index

| Scenario | Deployment | Usage | Source |
|----------|------------|-------|--------|
| Minecraft Game Agent | [en](scenarios/game/minecraft/en/deployment.md) / [zh](scenarios/game/minecraft/zh/deployment.md) | [en](scenarios/game/minecraft/en/usage.md) / [zh](scenarios/game/minecraft/zh/usage.md) | [bridge_server.js](scenarios/game/minecraft/bridge_server.js) |

### Version Info

- Project Version: v0.0.3 (rebuilt from PhyAgentOS v0.1.4)
- Document Version: v2.0
- Last Updated: 2026-06-11
