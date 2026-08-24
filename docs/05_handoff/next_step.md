# 下一步（Next Step）

> 只保留未完成任务，按优先级。

## 🔴 P0 — 全部改动待真机验证

以下改动均已离线验证通过，**尚未真机验证**：

- Scenario 层重构 + 第四次交接 4 项改动（TX/RX 时间戳、exec_async 去哨兵、RTMP heartbeat、测试结束询问）
- 20260824 改动：normal 移除重复 ftp task、修复 `--no-interactive-wifi` 断链、WiFi 职责重划（ADR-008）、depends 字段清理（ADR-009）

```bash
python3 -m ATS.main --scenario normal --no-interactive-wifi   # 先通正常链路
python3 -m ATS.main --scenario stress --no-interactive-wifi   # 再通压测循环
```

## 🟡 P1 — base.py docstring 过时（代码内注释，待 Code Agent）

`ATS/modules/base.py` 的 docstring 仍写旧语义，与 ADR-005/009 不符：

- L4：「声明 `name` 和 `depends`」→ depends 语义已变，可简化为「声明 `name`」。
- L54：「依赖的模块名列表（runner 据此拓扑排序）」→ **两处过时**：①「拓扑排序」早已改为「声明顺序执行」；② depends 已由 ADR-009 定义为「运行时 task 间 fail-fast」。

正确语义（照 ADR-009）：`depends` 只表达「运行时 task 间 fail-fast」（当前三场景均无此用法，字段保留但空）；逻辑依赖由 Scenario 的 prepare 编排 + `module_design.md` 表达。

## 🟡 P2 — loop 语义局限

当前 loop 只能循环「整轮 tasks」，不支持「A 任务循环 N 次 + B 只跑 1 次」混合编排（目前靠 task.repeat + scenario.loop 两层凑合）。

## 🟡 P3 — 破坏性 CLI 变更

`--modules`/`--skip` 已移除，`--scenario` 成为主入口。旧文档命令全部失效，需同步。

## 🟢 P4 — RTMP 类型2 网络异常未覆盖

heartbeat 只能证明「板端编码线程活着」，证明不了「网络断但板端仍在编码」（f_index 持续但 ffprobe 收不到）。如需覆盖需补周期 ffprobe 复探。
