# Windows CLI 分支状态（feature/windows-cli）

> 本文件是**分支专属** handoff，短期不会合入 `new_arch`。
> 主线 handoff（`current_status.md` 等）在本分支保持不动，避免同步冲突。
> 分支文档隔离约定见本文件「分支定位」与 [windows_cli_next_step.md](windows_cli_next_step.md)。

## 分支定位

- 从 `new_arch` 拉出，当前与 `new_arch` **完全同点**（0 ahead / 0 behind）。
- 目标：让上位机自动化测试脚本在 **Windows 下可用**（CLI 形态）。
- 短期不合主线：分支文档全部走专属文件，不碰主线 handoff / 共享索引 / ADR 编号。

## 代码现状

- **P0 已实施**（devlog `20260920_1502`）：新增 `ATS/platform/`（`serial_ports.py`/`console_input.py`/`processes.py`/`resources.py`）+ 六处业务文件接入（serial_console/serial_terminal/preview_manager/rtmp_receiver/h265_validator/logger）。
- **真机验证（2026-09-20，stress 场景）**：
  - ✅ 串口枚举（COM10@2000000 探测命中）、WiFi 连接、FTP 控制连接、ffplay 拉起（preview worker 启动）、logger VT 模式均正常。
  - ✅ **FTP 数据连接超时已修复且真机复验通过**：根因为 Windows 防火墙规则三字段错配（RemoteAddress/LocalAddress/Program 全错），修复后真实 FTP LIST 恢复 0.21s，完整 stress 复验无问题。详见「真机已知问题」#1 与 [排查报告](../03_development/archive/Windows_CLI_FTP主动模式超时_排查与解决报告.md)。
- **P1 离线测试未落地**：`tests/windows_cli/` 未创建，`.gitignore` 的 `/tests/` 未解除。
- 可复用参照：
  1. `origin/feature/ats-ui-windows` 的 `ATS/platform/` 抽象层（`serial_ports.py` / `console_input.py` / `processes.py`，已核实存在且可读）。
  2. `.ats_cli_backups/20260916_143611_3152bae7/install_record.json`：记录过一套 `applied` 状态的 CLI 移植清单（`ATS/platform/` 5 文件 + ADR-012 + 测试），但正文已丢失，仅存文件清单与 sha256。

## 影响分析结论（Linux 专属依赖点）

| # | 文件 | 问题 | 严重度 |
|---|------|------|--------|
| 1 | `core/serial_console.py` L508/L586 | `glob("/dev/ttyUSB*")` 硬编码，Windows 无 `/dev` | 🔴 阻塞 |
| 2 | `tools/serial_terminal.py` L20-21 | `import termios, tty` Windows 直接 ImportError | 🔴 阻塞 |
| 3 | `drivers/preview_manager.py` L207/L228-239 | `preexec_fn=os.setsid`（无此参数会 ValueError）、`os.killpg`/`os.getpgid` | 🔴 阻塞 |
| 4 | `drivers/preview_manager.py` L204/L178 | `["bash","-c",script]` + 终端模拟器候选全 Linux | 🟡 |
| 5 | `drivers/preview_manager.py` L118 | 依赖 `DISPLAY` 环境变量 | 🟡 |
| 6 | `core/logger.py` L120-134 | ANSI 颜色码直接 `print`（旧控制台乱码） | 🟡 |
| 7 | `rtmp_receiver.py` / `h265_validator.py` | ffprobe/ffmpeg 查找路径写死 `/usr/bin/...`（Windows 为 `.exe`） | 🟡 |

其余（`ftp_client.py`、`modules/*`、`config/` 大部分）用标准库，跨平台可用。`modules/*` 串口交互均走 `SerialConsole`，修好 #1 即复用。

## 决策状态（已定案）

1. **实现方式**：**方案 A**（抽 `ATS/platform/` 平台抽象层）。
2. **RTMP 服务端**：本机已启动 nginx-rtmp-win32-dev（监听 1935），`rtmp_server.py` 零改动可用。
3. **preview**：仍用 ffplay，改造 `preview_manager.py` 进程管理为 Windows 方式。
4. **cancellation 依赖**：裁剪（不引入 `core/cancellation.py`），`processes.py` 只留 `start`/`terminate`/`creation_kwargs`。
5. **工具查找统一**：引入 `resources.py`（`ResourceLocator.find_tool()`），ffprobe/ffmpeg/ffplay 三处统一走它。
6. **ANSI 颜色**：`ctypes` + `SetConsoleMode` 启用 VT（零第三方依赖）。
7. **preview 注入方式**：构造注入（测试可传 mock）。

完整设计见 [02_design/windows_cli_port_plan.md](../02_design/windows_cli_port_plan.md)。

## 架构影响

- 方案 A 属 **Level 3**（新增平台适配层），合主线时需 ADR（编号届时再定，分支上不抢号）。
- 方案 B 属实现级，devlog 留痕即可。
- 两者均不破坏主线主链 `config → ScenarioManager → Runner → Module → Driver`。

## 真机已知问题

| # | 现象 | 根因 | 状态 |
|---|------|------|------|
| 1 | FTP LIST 反复超时（`FTP list 失败: timed out`），photo 每项耗时 ~68s，压测缓慢如卡死 | Windows 防火墙规则 `Gravity ATS CLI FTP - Board101` **三字段错配**：`RemoteAddress=.101`（EVB 实为 .100）、`LocalAddress=.100`（把 EVB 当本机，本机实为 .103）、`Program=系统python`（实际用 venv python）→ 规则与实际流量（.100 回连 .103 高位端口）方向完全相反，放行从未生效 | ✅ **已修复并真机复验通过**（规则改为 `RemoteAddress=.100`/`LocalAddress=Any`/`Program=Any`/`LocalPort=1024-65535`，真实 FTP LIST 恢复 0.21s，完整 stress 复验无问题） |

> 详细排查见 [archive/Windows_CLI_FTP主动模式超时_排查与解决报告.md](../03_development/archive/Windows_CLI_FTP主动模式超时_排查与解决报告.md)、devlog `20260920_1600`。
> 主线 `build_environment.md` 早已提示「防火墙放行 1024-65535 高端口（FTP 主动模式 + RTMP 1935）」，本分支在 Windows 上未落实此条，现已修复。

## 待办（Code Agent）

- **preview 窗口尺寸可配置（方案 A）**：Windows 下 ffplay 画面窗口过大（跟随视频原始分辨率）且无法 resize/移动。方案 A：`preview_manager.py` 的 `_argv()` 加 `-x/-y`（值从 `preview.yaml` 的 `window_width`/`window_height` 读，默认 960/540）。详见 [windows_cli_next_step.md](windows_cli_next_step.md)。
