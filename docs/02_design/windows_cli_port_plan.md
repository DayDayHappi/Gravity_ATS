# Windows CLI 移植设计（分支专属，合主线时升正式 ADR）

> 本文件是 `feature/windows-cli` **分支专属**设计文档，短期不合入 `new_arch`。
> 合主线时由 Document Agent 升级为正式 ADR（编号届时再定，分支上不抢主线编号）。
> 决策依据与分支隔离约定见 [05_handoff/windows_cli_status.md](../05_handoff/windows_cli_status.md)。

## Background（背景）

上位机自动化测试脚本原为 Linux 专属：串口枚举硬编码 `/dev/ttyUSB*`、交互终端依赖 `termios/tty`、画面观察进程管理依赖 `bash -c` + `setsid`/`killpg`。需在 Windows 下可用（CLI 形态）。

本分支与 `new_arch` 当前同点，适配从零实施。参照物为 `origin/feature/ats-ui-windows` 的 `ATS/platform/` 抽象层（已核实存在）。

## Problem（问题）

Windows 无 `/dev` 设备树、无 `termios/tty`、无 `os.setsid`/`os.killpg`（进程组信号）、无 `bash`（默认）。直接运行会在三处崩溃或行为错误：

| # | 文件 | Linux 专属点 |
|---|------|-------------|
| 1 | `core/serial_console.py` | `glob("/dev/ttyUSB*")` |
| 2 | `tools/serial_terminal.py` | `import termios, tty` |
| 3 | `drivers/preview_manager.py` | `preexec_fn=os.setsid`、`os.killpg`、`["bash","-c",script]` |

## Decision（决策）

**方案 A：新增 `ATS/platform/` 平台抽象层**，把 OS 差异集中到独立文件，业务代码调用抽象接口，不做 `if os.name` 判断。

已定决策清单（全部已定案）：

1. **实现方式** = 方案 A（平台抽象层）。
2. **RTMP 服务端** = 本机 nginx-rtmp-win32-dev（监听 1935），`rtmp_server.py` 零改动。
3. **preview** = 仍用 ffplay，进程管理走平台抽象层。
4. **cancellation 依赖** = 裁剪（方案甲）：`processes.py` 去掉 `CancellationToken` 相关参数与逻辑，只留 `start`/`terminate`/`creation_kwargs`；不引入 `core/cancellation.py`。
5. **工具查找统一** = 引入 `resources.py`（`ResourceLocator.find_tool()`），ffprobe/ffmpeg/ffplay 三处统一走它（自动处理 `.exe` 后缀 + PATH + bundled 目录）。
6. **ANSI 颜色** = `ctypes` 调 `SetConsoleMode` 启用 `ENABLE_VIRTUAL_TERMINAL_PROCESSING`（Win10+，零第三方依赖）。
7. **preview 注入方式** = 构造注入（ui-windows 写法，测试可传 mock）。

离线测试策略见下文「测试策略」。

## 平台抽象层设计

### 目录结构

```
ATS/platform/
├── __init__.py          # 导出三个核心类
├── serial_ports.py      # PySerialPortProvider + SerialPortInfo
├── console_input.py     # create_console_key_reader()
└── processes.py         # ProcessController
```

### 1. serial_ports.py — 串口枚举

```python
@dataclass(frozen=True)
class SerialPortInfo:
    device: str
    description: str = ""
    hwid: str = ""
    vid: Optional[int] = None
    pid: Optional[int] = None
    # ... is_bluetooth / is_usb / display_name 属性

class PySerialPortProvider:
    def list_ports(self) -> List[SerialPortInfo]: ...   # 基于 serial.tools.list_ports.comports()
    def candidate_names(self) -> List[str]: ...         # 仅返回 device 名（COMx / /dev/ttyUSB*）
```

- 用 `serial.tools.list_ports.comports()`，Linux 返回 `/dev/ttyUSB*`、Windows 返回 `COMx`，一处兼容。
- 蓝牙端口过滤 + USB 优先排序（照抄 ui-windows，接口已稳定）。

### 2. console_input.py — 交互终端单键读取

```python
def create_console_key_reader(platform_name=None, stream=None):
    # windows -> msvcrt.getwch()
    # posix   -> termios.tcgetattr + tty.setcbreak
    # 非 tty  -> stream.read(1) 兜底
    # 返回上下文管理器，用法：with create_console_key_reader() as r: r.read_key()
```

- 关键：`termios`/`msvcrt` 的 import 都在**各自 reader 类内部**（延迟 import），避免顶层 `import termios` 在 Windows 崩。

### 3. processes.py — 子进程生命周期

```python
class ProcessController:
    @property
    def is_windows(self) -> bool: ...

    def creation_kwargs(self, *, new_process_group=True, show_window=False) -> dict:
        # windows: creationflags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        # posix:   start_new_session=True

    def start(self, argv, *, new_process_group=True, show_window=False, **kwargs) -> Popen:
        # 强制 shell=False，argv 必须是 list（禁 shell 字符串）

    def terminate(self, proc, grace=2.0) -> None:
        # windows: taskkill /PID <pid> /T  ->  /F 兜底
        # posix:   os.killpg(os.getpgid(pid), SIGTERM) -> SIGKILL 兜底
        # 最后 proc.wait(grace) 回收，不留僵尸

    def run_capture(self, argv, *, timeout=None, text=True, **kwargs) -> CompletedProcess:
        # 带 timeout 的捕获执行（供 ffprobe/ffmpeg 类场景复用，可选）
```

## 业务文件接入点（相对 new_arch 的净差异）

| 文件 | 接入方式 | 差异面积 |
|------|---------|---------|
| `core/serial_console.py` | `_list_candidate_ports(port_provider=None)`：默认 lazy import `PySerialPortProvider()`，返回 `candidate_names()`；删掉 `glob.glob("/dev/...")` | 1 函数替换 |
| `tools/serial_terminal.py` | `with create_console_key_reader() as r:` 逐字符 `r.read_key()`；删掉顶层 `import termios/tty` 与 `tcgetattr/setcbreak` | 读字符逻辑替换 |
| `drivers/preview_manager.py` | 注入 `ProcessController` + `ResourceLocator`；ffplay 查找走 `find_tool()`；启动走 `_processes.start()`、回收走 `_processes.terminate()`；删除 `bash -c` wrapper + `setsid`/`killpg` | 进程管理逻辑替换 |

> 接入方式已对照 `origin/feature/ats-ui-windows` 核实：`serial_console` 用「函数可选参数 + lazy import」、`serial_terminal` 用「上下文管理器」、`preview_manager` 用「构造注入」。

## 与 ui-windows 的裁剪关系（重要）

ui-windows 的 platform 层还含 `resources.py` / `desktop.py` / `rtmp_backend.py` / `services.py` / `serial_registry.py`，且 `processes.py` 依赖 `core.cancellation.CancellationToken`。本分支是 **CLI 最小裁剪版**：

| ui-windows 模块 | 本分支是否引入 | 说明 |
|----------------|--------------|------|
| `serial_ports.py` | ✅ 引入 | 直接可用 |
| `console_input.py` | ✅ 引入 | 直接可用 |
| `processes.py` | ✅ 引入（裁剪） | 去掉 `CancellationToken` 依赖，或一并移植 `core/cancellation.py`（见下） |
| `resources.py` 的 `find_tool()` | ✅ 引入（仅此能力） | 统一 ffprobe/ffmpeg/ffplay 的 `.exe` 查找 |
| `desktop.py` / `rtmp_backend.py` / `services.py` / `serial_registry.py` | ❌ 不引入 | GUI/服务编排专用，CLI 不需要 |

**cancellation 依赖已定案（方案甲）**：`processes.py` 去掉 `CancellationToken` 相关参数与逻辑（`wait`/`run_capture` 的取消轮询），只留 `start`/`terminate`/`creation_kwargs`；**不引入** `core/cancellation.py`。`run_capture` 若需超时打断，用 subprocess 自带 `timeout`，不引入取消令牌。

## 收尾项（非平台层，但同属适配）

| # | 文件 | 改动 |
|---|------|------|
| 1 | `core/logger.py` | Windows 控制台用 `ctypes` 调 `SetConsoleMode` 启用 `ENABLE_VIRTUAL_TERMINAL_PROCESSING` 后再打 ANSI 色（Win10+，零第三方依赖） |
| 2 | `rtmp_receiver.py` | ffprobe 查找走 `ResourceLocator.find_tool()`（兼容 `.exe` 与 PATH） |
| 3 | `h265_validator.py` | ffmpeg 查找走 `ResourceLocator.find_tool()`（兼容 `.exe`） |

## 测试策略（已定案：写离线测试 + 解除 `/tests/` 忽略）

platform 层是纯逻辑抽象，适合离线单测。本分支落地：

1. **解除 `/tests/` 忽略**：`.gitignore` 中 `/tests/` 改为放行（或仅放行 `tests/windows_cli/`）。
   - ⚠️ 合主线时需复核：主线此前刻意忽略 `/tests/`，本分支解除是分支专属行为。
2. **测试目录** `tests/windows_cli/`：
   - `test_platform.py`：`PySerialPortProvider`（mock 枚举器，覆盖 COM/tty 双形态）、`create_console_key_reader` 三态分派、`ProcessController.creation_kwargs`（win/posix 两分支）。
   - `test_lifecycle.py`：`ProcessController.start/terminate` 进程树回收（posix 真实进程 + win 分支用 mock taskkill 断言）。
   - `test_cli.py`：`--list-modules` / `--list-scenarios` / `--dry-run` 跨平台可跑。
   - `test_regression.py`：主线既有离线回归（`detect_port` / `SerialConsole` 哨兵 / ADR-013 指纹分派）不受平台层影响。

> 参照 ui-windows 的 `tests/windows_cli/`（`test_cli.py` / `test_lifecycle.py` / `test_platform.py` / `test_regression.py` 已存在），按 CLI 最小裁剪取舍。

## Alternative（备选：方案 B）
`if os.name == "nt"` 内联条件分支，不新增层级。

- 优点：改动最小、无新架构层级、见效快。
- 缺点：OS 分支散落 3 处、单测需 mock `os.name`、未来 GUI/多平台需二次重抽、与 new_arch 高频文件（尤其 serial_console）的行级冲突面大。
- 否决理由：本分支后续长期与 new_arch 反复同步，方案 B 的 OS 代码内联在高频业务文件里，每次 pull 易冲突且难解；方案 A 把 OS 代码隔离进主线不存在的新目录，同步零冲突。

## Impact（影响）

- **架构层级**：Driver 之下新增平台适配层（Level 3，合主线时需 ADR）。
- **主链不动**：`config → ScenarioManager → Runner → Module → Driver` 完全保留，模块红线/ADR-011 协议集中化/ADR-013 指纹分派均不受影响。
- **对外 API 不变**：`detect_port` / `SerialConsole` / `run_terminal` / `PreviewManager.start/stop` 签名不变。
- **RTMP 服务端**：零改动（`rtmp_server.py` 只做 127.0.0.1:1935 就绪探测）。

## Status

Proposed（分支专属设计文档；合主线时升正式 ADR，Status 届时改 Accepted）。
