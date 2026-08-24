# ADR-009：depends 字段语义定位（只做 task 间 fail-fast，逻辑依赖移到文档）

## Background

ADR-008 实施后，`ftp` / `wifi_join` / `wifi_check` / `wifi_scan` 退出 task 流，导致多个模块内联声明的 `depends` 变成死字段：

| 模块 | 死依赖 | 实际前置由谁保证 |
|------|--------|-----------------|
| photo / video | `depends = ["ftp"]` | prepare.ftp_ready |
| rtmp / ftp | `depends = ["wifi_join"]` | prepare.wifi_connect |
| wifi_scan | `depends = ["wifi_check"]` | prepare 内部 |
| wifi_join | `depends = ["wifi_scan"]` | 已退出 normal |

Runner 的 fail-fast 只在 `module_status` 里找到依赖模块时才 SKIP，而这些依赖目标已不在 task 流中，故 `depends` 无任何运行时效果。

## Problem

`depends` 字段语义模糊：它到底表达「逻辑依赖」（谁需要谁的前置环境），还是「运行时 task 间 fail-fast」？两种语义混在一个字段里，导致「逻辑依赖」被写死在模块代码中，与 ADR-005/007「依赖由 Scenario 表达」的哲学冲突。

## Decision

**方向 A：清理死依赖，depends 字段单一化。**

1. 清空所有模块的 `depends`（改为 `[]`）——包括 photo/video/rtmp/ftp/wifi_scan/wifi_join。
2. `depends` 字段从此**只表达「运行时 task 间 fail-fast」**（当前三个场景均无此用法，字段保留但空）。
3. 「逻辑依赖」（如 photo 需要 FTP 就绪、rtmp 需要 WiFi 就绪）**移出代码**，改由：
   - Scenario 的 prepare/tasks 编排表达（prepare 保证前置环境）；
   - `module_design.md` 的 Dependency 描述表达（文档记录逻辑依赖）。

## Alternative

- **方向 B（保留死依赖）**：保留 depends 作为「逻辑依赖声明」，文档注明已无运行时效果。好处是未来复用 wifi_scan/join 链无需恢复；坏处是代码里残留误导性死字段，语义继续含糊。

## Impact

- 6 个模块的 `depends` 清空为 `[]`。
- fail-fast 机制保留，但当前无场景触发（未来若某场景需要 task 间依赖，需重新声明 depends 或在 Scenario 层表达）。
- 逻辑依赖信息集中到 `module_design.md`，代码更纯粹（模块只做动作，见 ADR-007）。

## Status

Accepted（源码清理待 Code Agent）
