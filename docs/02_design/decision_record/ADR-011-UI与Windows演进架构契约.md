# ADR-011：UI 与 Windows 演进架构契约

- Status: Accepted for Phase 0 design freeze
- Date: 2026-09-04
- Scope: Gravity_ATS / `new_arch`
- Related plan: `Gravity_ATS_UI_Windows_开发计划_v1.0_20260904.md`

## Background

Gravity_ATS 当前核心执行链已经形成稳定分层：

```text
config（三层）
    ↓
ScenarioManager（prepare / tasks / cleanup）
    ↓
Runner（cycle / repeat / retry / fail-fast 调度）
    ↓
Module（测试动作与业务判据）
    ↓
Driver / Context（串口、FTP、RTMP、FFmpeg 等底层能力）
```

后续目标是在不复制业务代码、不改变现有 Scenario 语义和测试判据的前提下，引入桌面 GUI，并最终运行于 Windows。该变化涉及表现层、用例入口、生命周期、取消机制及平台边界，属于架构级变化，因此在实现 Phase 1 前先冻结契约。

## Decision

### 1. 依赖方向

长期依赖方向冻结为：

```text
CLI / GUI / future Web API
          ↓
     Application
     TestService
          ↓
 Existing ATS Engine
 Scenario → Runner → Module
          ↓
   Driver / Context
          ↓
    Platform Services
```

禁止反向依赖：

- Core / Module / Driver 不得 import GUI / PySide6。
- Module 不得持有窗口、控件或 GUI Worker Thread。
- GUI 不得直接实例化具体 TestModule。
- GUI 不得直接操作 Runner 内部状态。
- GUI 不得直接控制 SerialConsole 的测试生命周期。
- GUI 不得通过解析 `run.log` 文本判断 PASS / FAIL。
- Windows 支持不得通过复制一套 `modules/` 或 Scenario 实现完成。
- Core / Module 不得散布大量 `os.name` / `platform.system()` 平台分支。

### 2. TestService 契约

`TestService` 是 CLI、GUI、未来 Web API 共用的 Application 入口。

职责：

- 接收 `RunRequest`。
- 加载并协调现有 Scenario / Runner 执行。
- 接入 Interaction、Event、Cancellation 等 Application 能力。
- 返回 `RunResult`。
- 保持既有报告、日志和退出语义可映射。

非职责：

- 不重新实现 Module 业务判据。
- 不复制 Scenario 调度逻辑。
- 不把 GUI 控件类型传入 Core / Module。
- 不把 Windows/Linux 具体进程、路径、串口枚举逻辑散布给业务模块。

### 3. RunRequest / RunResult 契约

`RunRequest` 用于描述“一次测试请求”，至少覆盖：

- scenario
- system/runtime overrides
- module overrides
- output directory override
- execution options

它是 YAML 配置体系之上的运行时输入，不建立第二套“模块启用/顺序”配置体系。

`RunResult` 用于描述“一次测试执行结果”，必须能够承载：

- run identity / scenario
- 测试结果集合（继续复用或等价承载现有 `TestResult`）
- 运行终态
- 报告/产物位置
- 可映射到既有 CLI 退出语义

Phase 0 只冻结职责和最小数据边界，不提前冻结尚未实现的具体 Python 构造函数签名。

### 4. EventSink / EventBus 契约

结构化事件是观察通道，不拥有业务控制权。

- Runner / Application 产生生命周期事件。
- UI 订阅事件显示实时状态。
- 事件监听器异常不得反向导致 ATS 主测试失败。
- 未注册 EventSink 时，ATS 行为应与基线一致。
- `run.log` / `serial.log` 继续用于归档追溯，不作为 UI 业务状态协议。
- `serial.log` 保持原始串口收发性质，事件机制不得污染它。

### 5. CancellationToken 契约

取消必须是协作式、安全停止：

- `cancel()` 发出请求。
- `is_cancelled` / 等价查询用于安全点检查。
- `raise_if_cancelled()` / 等价机制用于统一中止控制流。
- Runner、长耗时 Module、子进程操作在安全点响应取消。
- STOP 不得通过强杀 GUI Worker Thread 绕过 `teardown` / scenario `cleanup`。

具体安全点与响应上限在 Phase 3 冻结和实现。

### 6. InteractionProvider 契约

所有需要人工输入/确认的交互，经 `InteractionProvider` 抽象：

- CLI 实现可使用 stdin/TTY。
- GUI 实现使用对话框/控件。
- TestService / Core / Module 不直接依赖 GUI 控件。
- Phase 1 完成后，Application 入口应可在普通 Python 调用环境运行，不要求 stdin/TTY。

### 7. ResourceLocator 契约

资源路径解析统一归口：

- app root
- config
- runtime tools（ffmpeg / ffprobe / ffplay）
- logs
- reports
- user/runtime override data

目标是消除“必须从项目根目录作为 cwd 启动”的隐式前提。具体实现属于 Phase 4。

### 8. Platform Services 契约

只抽象真实 OS 差异，初始边界包括：

- `SerialPortProvider`：跨平台串口枚举。
- `ProcessController`：子进程启动、终止、进程树回收。
- RTMP Server Backend / readiness：业务模块只关心“服务已就绪”。
- 必要的 terminal / process / resource platform adapter。

EVB 协议、2,000,000 baud、`health_check`、`exec_sync` / `exec_async` 等业务/设备语义不得因为 Windows 产生两套实现。

## Existing Behavior That Must Not Change During Phase 0

Phase 0 不修改以下生产行为：

- Scenario → Runner → Module → Driver 分层。
- normal/stress/video_integrity 的 YAML 编排语义。
- photo 既有成功判据。
- video 既有成功判据。
- rtmp 的 ffprobe + heartbeat 主判据。
- video_integrity / H265Validator 的既有诊断与判定算法。
- `serial.log` 原始串口记录性质。
- 现有 JSON / JUnit / HTML 报告格式与生成职责。

## Linux-specific Boundaries Registered for Later Phases

Phase 0 只登记、不修改：

1. `/dev/ttyUSB*`、`/dev/ttyACM*` 枚举。
2. `ATS/tools/serial_terminal.py` 的 `termios` / `tty` cbreak 终端控制。
3. PreviewManager 的 `DISPLAY` 检查。
4. PreviewManager 的 bash 重连 wrapper。
5. `os.setsid` / `os.killpg` POSIX 进程组控制。
6. Linux terminal emulator 启动方式。
7. nginx-rtmp + systemd / apt 部署假设。
8. `tools/ffmpeg/...` 相对 cwd 路径及 Linux 常见绝对路径探测。

处理策略详见 `docs/04_testing/phase0_baseline_freeze.md`。

## Consequences

### Positive

- CLI、GUI、未来 Web API 共享一套测试引擎。
- Windows 差异被限制在平台/资源层。
- Module 判据与 Scenario 数据驱动机制可以保持稳定。
- 后续 Event / Cancellation 能独立演进，不把日志文本变成业务协议。

### Cost

- Phase 1~4 必须先建立 Application / Event / Cancellation / Platform 边界，不能直接在现有 `main.py` 外包一层 PySide6 窗口。
- 部分现有 Linux-only 工具需要在后续阶段替换或适配。

## Rejected Alternatives

1. **GUI 直接调用 Module / Runner**：短期快，但把表现层与测试引擎绑定，拒绝。
2. **Windows 复制一套 modules/scenarios**：形成双业务基线，拒绝。
3. **UI 解析 run.log 获取状态**：日志文本不是稳定协议，拒绝。
4. **Core/Module 到处加平台 if/else**：平台耦合扩散，拒绝。
5. **Phase 0 直接开始写 TestService/PySide6**：违反阶段门禁，拒绝。

## Phase Gate

进入 Phase 1 前必须同时满足：

- 真实仓库建立明确 baseline commit/tag；
- normal / stress / video_integrity / dry-run / list 命令形成实际运行记录；
- `phase0_baseline_freeze.md` 中外部验证项关闭；
- 不存在未解释的基线行为漂移。
