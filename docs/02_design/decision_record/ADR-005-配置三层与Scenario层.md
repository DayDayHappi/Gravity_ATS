# ADR-005：配置三层拆分 + Scenario 层引入

## Background

原架构是单一 `test_config.yaml` + `enabled_modules` 列表，无法表达压测 / 老化等复杂编排（循环、持续时间、多轮组合）。

## Problem

配置与编排耦合，加新场景要改代码；无法复用模块实现不同测试策略。

## Decision

- **配置拆三层**：system（环境级）/ modules（模块参数）/ scenarios（测试策略）。
- **引入 Scenario 层**：prepare → tasks(loop) → cleanup；Task 支持 repeat/duration；loop 支持 count/duration/无限。
- **模块 run(params) 参数入口**，持续参数经 `duration_key` 覆盖。
- **职责边界**：Scenario=怎么组合，Runner=什么时候执行，Module=怎么测，Config=参数是什么。

## Alternative

- 扩展 enabled_modules 列表：表达不了循环/时长/多轮。
- 模块内写循环：违反模块红线，加新场景要改模块。

## Impact

核心框架重构（scenario / scenario_manager / runner / config）；模块核心逻辑零改动。

## Status

Accepted
