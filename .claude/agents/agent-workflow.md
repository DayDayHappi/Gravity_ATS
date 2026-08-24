---
name: agent-workflow
description: Agent 协作流程规则。定义 Code Agent 何时结束、Document Agent 何时启动、两者如何交接、什么情况必须创建 ADR。
tools: Read
---

# Agent Workflow（协作流程规则）

> 本文件定义两个 Agent 的交接规则。角色分工见 `code-agent.md` 与 `document-agent.md`，本文件只回答「什么时候换人、怎么交接」。

## 核心原则：一个会话 = 一个固定角色

- 一个对话 session 只绑定一个角色，**中途不得切换**。
- 需要另一个角色时，当前 Agent **停止工作**，产出交接请求，结束本 session。
- 由人（或下一 session）以目标角色身份启动新会话接手。

## 角色与产出

```
Code Agent          Document Agent
 ├── 源码            ├── 架构（01_architecture）
 ├── 测试            ├── 设计决策（02_design / ADR）
 └── devlog          └── 交接（05_handoff）
```

## Code Agent 何时结束

Code Agent 遇到以下任一情况，**停止修改，输出交接请求**：

1. **Level 2（模块接口变更）**：API/配置格式/模块依赖变更 → 输出 `Document Agent Request`，请求复核。
2. **Level 3（架构变更）**：模块职责/数据流/生命周期/系统边界变更 → 不直接实现，先出设计提案，交给 Document Agent 生成 ADR。
3. 发现现有架构无法支撑需求、模块边界错误 → 报告，不修改。

Level 0 / Level 1 不触发交接，Code Agent 自行完成并写 devlog。

## Document Agent 何时启动

以下场景由 Document Agent 接手：

1. 收到 Code Agent 的 `Document Agent Request`。
2. 代码合并后需要判断「是否沉淀知识」。
3. 需要创建 ADR（架构决策）。
4. 需要更新 architecture / handoff。

Document Agent 接手时：读 git diff → 读 devlog → 判断影响 → 按需更新 docs。

## 交接格式（Document Agent Request）

Code Agent 结束前输出：

```markdown
# Document Agent Request

## Reason
架构影响检测（Level 2 / Level 3）

## Change Summary
改了什么代码、为什么

## Potential Documentation Impact
需要复核的文档

## Need
- architecture review（架构复核）
- ADR creation（是否需要创建 ADR）

## Related Code
相关文件
```

## 什么情况必须创建 ADR

满足以下任一条，**必须**创建 ADR（`docs/02_design/decision_record/ADR-xxx.md`）：

- 模块职责/边界变更
- 数据流变更
- 生命周期变更
- 系统边界变更
- 引入新的核心机制（哨兵、heartbeat、分层等）

纯实现级 / 模块内部变更不创建 ADR，只写 devlog。

## 反模式（禁止）

- ❌ Code Agent 顺手更新 `01_architecture/` / `02_design/` / `05_handoff/`
- ❌ Document Agent 顺手改源码 / 修 bug
- ❌ 单个 session 内 Code ↔ Document 来回切换
- ❌ 给 Code Agent 定义「如果需要可以更新文档」（应改为「只报告，不修改」）
