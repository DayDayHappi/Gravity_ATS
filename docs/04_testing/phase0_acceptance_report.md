# Phase 0 客观验收报告

- Date: 2026-09-04
- Basis: `Gravity_ATS_UI_Windows_开发计划_v1.0_20260904.md` Phase 0
- Source reviewed: 2026-09-04 最新 `all_source.txt`
- Overall verdict: **CONDITIONAL / NOT YET FULL PASS**

## 1. 验收原则

本报告严格区分：

1. 可以通过源码静态阅读证明的事项；
2. 必须在真实 Git 仓库或真实运行环境中产生证据的事项。

第二类若没有真实证据，不以“代码看起来可以”代替 PASS。

## 2. 逐项验收

| # | 开发计划验收项 | 结果 | 客观证据/说明 |
|---:|---|---|---|
| 1 | 建立明确 baseline commit/tag，并记录 `new_arch` | **BLOCKED** | 当前仅有源码快照，无法读取你的真实仓库当前 HEAD/dirty state，也不能代表你创建 Git tag。必须在真实 repo 执行。 |
| 2 | normal、stress、video_integrity、dry-run、list-scenarios、list-modules 有可复现基线记录 | **BLOCKED** | 入口和静态行为已核实，但未在你的 EVB/本机环境实际执行并保存证据。项目现有 handoff 也明确存在 normal/stress/Preview 等待真机项，因此不能伪造运行 PASS。 |
| 3 | 记录 task 顺序、cycle/repeat、报告目录、日志目录、退出码 0/1/2 | **PASS（静态）** | 已冻结于 `phase0_baseline_freeze.md`，直接按当前 main/Scenario/Runner/logger/reporter 源码记录。 |
| 4 | Linux 特定依赖清单并标注保留/抽象/替换 | **PASS** | 已登记 `/dev`、termios/tty、DISPLAY、bash、setsid/killpg、terminal emulator、nginx-rtmp/systemd、相对 FFmpeg 路径、FTP firewall 等，并给出对应后续阶段策略。 |
| 5 | 架构禁止 GUI 直接调用 Module/SerialConsole、解析 run.log 判定 PASS/FAIL | **PASS** | ADR-011 已明确冻结依赖方向和禁止项。 |
| 6 | 未为 UI 改动 photo/video/rtmp/video_integrity 业务判据 | **PASS** | 本 Phase 0 产物没有修改 `ATS/` 下任何生产源码，也没有修改这些 Module/Driver/YAML 的业务判据。 |
| 7 | 架构变化按 Agent 治理完成 ADR 后方可 Phase 1 | **PASS（设计产物） / Gate 仍关闭** | ADR-011 已形成；但根据 Phase 0 总 Gate，仍需 #1/#2 的真实仓库和运行证据完成后才能进入 Phase 1。 |

## 3. 生产代码变更审计

本 Phase 0 修改：

```text
ATS/**/*.py      0 files
ATS/config/**    0 files
业务判据          0 changes
Scenario语义      0 changes
```

这是预期结果，不是遗漏。Phase 0 的职责是“冻结基线与架构边界”，不是提前实现 Phase 1。

## 4. 发现的当前 Linux-only / 平台耦合点

### Critical for Windows

1. SerialConsole 自动候选串口只针对 `/dev/ttyUSB*` / `/dev/ttyACM*`。
2. 独立串口终端直接依赖 `termios` / `tty`，Windows 无该接口。
3. PreviewManager 依赖 `DISPLAY`、bash wrapper、POSIX `setsid/killpg`。
4. ffmpeg/ffprobe/ffplay 配置存在相对 cwd 定位假设。
5. RTMP Server 部署文档和错误提示绑定 nginx-rtmp/systemd/Ubuntu。

这些问题已经登记，但按计划应分别在 Phase 4/6/7 处理，Phase 0 不提前修改。

## 5. 当前基线风险

源码库现有 handoff 已明确若干能力仍“待真机验证”，特别是：

- normal/stress 所处基础链路仍有待真机确认项；
- ADR-010 PreviewManager 已实施但仍待真机验收；
- H265 接入 normal/stress 的 Case B/C 尚未真机闭环。

因此 Phase 0 的“当前可工作行为”必须以你实际运行后保存的 evidence 为最终事实，不能只凭历史文档或静态源码下结论。

## 6. Phase 0 最终 Gate

满足以下条件后，本报告可改为 `PASS`：

- [ ] 真实仓库 `new_arch` 工作树确认并记录 HEAD。
- [ ] 目标基线处于可追溯 commit。
- [ ] 创建 `gravity-ats-ui-win-phase0-baseline-20260904`（或你批准的等价名称）tag。
- [ ] 六组基线命令产生 evidence。
- [ ] normal/stress/video_integrity 的实际 exit code、日志/报告路径与本冻结文档无无法解释的漂移。
- [ ] 若发现漂移，先更新“基线事实”或修复现有缺陷，再重新冻结；不得带着未知漂移进入 Phase 1。

## 7. 结论

**当前可交付状态：Phase 0 的源码分析、架构契约冻结、Linux 依赖登记和静态行为基线已经完成；但整体 Phase 0 不能客观宣称 PASS。**

剩余阻塞均不是“还要继续写代码”，而是必须在你的真实仓库/真实运行环境完成的 Git 基线和运行证据操作。
