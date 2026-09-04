# Phase 0 — UI / Windows 迁移状态

- Date: 2026-09-04
- Branch target: `new_arch`
- Status: **GATE_PENDING_EXTERNAL_EVIDENCE**

## 已完成

- 阅读并按 UI/Windows 开发计划冻结 Phase 0 范围。
- 基于最新 `all_source.txt` 完成现有 CLI / Scenario / Runner / logging / reporting / exit semantics 静态基线。
- 完成 Linux-specific dependency inventory。
- 创建 ADR-011，冻结 TestService、RunRequest/RunResult、Event、Cancellation、Interaction、ResourceLocator、Platform Services 的职责边界。
- 明确依赖红线：GUI 不直接调用 Module/Runner/SerialConsole，不解析 run.log 判结果；生产 Module 不引入 PySide6；Windows 不复制业务模块。
- 未修改任何 `ATS/` 生产源码或业务判据。

## 未完成 / 外部 Gate

以下必须在真实 Gravity_ATS Git 仓库和实际运行环境执行：

1. 记录 `new_arch` 当前真实 HEAD 和工作树状态。
2. 确认基线代码已提交并创建 baseline tag。
3. 保存以下真实命令的运行 evidence：
   - normal
   - stress
   - video_integrity
   - `--dry-run`
   - `--list-scenarios`
   - `--list-modules`
4. 核对实际 task 顺序、cycle/repeat、exit code、日志/报告目录与冻结记录一致。

## Phase 1 Gate

在以上外部 Gate 全部关闭前：

**不要开始 TestService / Application 层生产代码改造。**

若基线运行发现现有代码本身有缺陷，应先按现有 Agent 规则处理并重新冻结基线，而不是把修复与 Phase 1 架构重构混在同一变更中。
