# 新增交互式串口终端模式（--terminal，类 Xcom）

## 背景

RTMP 调试中发现：EVB 的 `rtmp_video_start` 命令行为未知（可能卡死/可能需前置准备/可能路径问题），需要一个人工手动发命令、实时看板子返回的调试手段，像 Xcom 串口助手那样。现有 ATS 是自动化测试框架（命令-响应模型，exec_sync/exec_async），没有"人工实时交互"能力。

用户要全程手动操作：自己敲命令发到板子，屏幕实时显示 TX（发送）+ RX（板子返回），脚本不代发、不解析、不判定。

## 设计

### 独立工具，复用纯函数，不动 core 类

Xcom 模式与测试框架职责不同（调试 vs 自动化），采用**方案 B**：
- 新增 `ATS/tools/serial_terminal.py`（新目录 `tools/`，注意与项目根的 `tools/ffmpeg`、`tools/mediamtx` 区分，那个是二进制资产，这个是代码，放 `ATS/tools/`）
- **直接用 pyserial**：自己 `serial.Serial()` 开口 + 自己起读线程实时打屏，不碰 `SerialConsole` 类
- 复用两个**纯函数**（不依赖类实例）：
  - `ATS.core.serial_console.detect_port()` —— 自动探测串口（指纹+波特率回退）
  - `ATS.core.ansi.strip()` —— 剥离 ANSI 转义
- 入口：`main.py` 加 `--terminal` 子命令，像 `--list-modules` 那样早返回

### 交互行为（已与用户确认）

1. **启动**：`python3 -m ATS.main --terminal`
   - 复用配置的串口参数（port=auto 自动探测，baudrate 默认 2000000）
   - 支持 `--port`/`--baudrate` 覆盖
   - 连上后打印提示：端口、波特率、帮助（回车发送、Tab 切换 ANSI、Ctrl+C/E 退出）

2. **发送**：用户在终端敲一行命令，回车发送
   - 自动补 `\n`（msh 换行定界，不用 `;`）
   - 发送的内容立即以 `TX>` 前缀 + 绿色 显示在屏幕

3. **接收**：读线程实时把板子返回打到屏幕，`RX<` 前缀 + 默认色
   - 默认剥离 ANSI（`[33m...[0m` 颜色码），屏幕干净
   - **Tab 键切换**：剥离 ↔ 原始字节两种显示模式，状态行提示当前模式

4. **退出**：Ctrl+C 或输入 `exit`/`quit`

5. **TX/RX 区分**：`TX>` 绿色、`RX<` 默认色，前缀+颜色双重区分

### 关键实现点

- **读线程实时打屏**：daemon 线程循环 `ser.read()`，读到就 `ansi.strip`（若开启）后 print（带 `RX<` 前缀），用 `sys.stdout.flush()` 保证实时。注意 print 要处理换行不重复（板子返回自带换行时不再加）。
- **主线程阻塞读 stdin**：`input()` 阻塞等用户输入，回车后 `ser.write(cmd + "\n")` + 打印 `TX>`。
- **ANSI 切换**：读线程读一个共享 `strip_ansi` 标志（bool），Tab 键在主线程切换它。但 `input()` 阻塞时 Tab 会被当成普通输入——所以 Tab 切换需用**非阻塞键盘读取**。
  - 简化方案：不做运行中 Tab 切换（input 阻塞挡住），改为**启动参数 `--raw`** 控制是否剥离，运行中固定。这更简单可靠，符合 Xcom（Xcom 也是启动设好参数）。
  - **修正**：用户选了"Tab 切换"。但 input() 阻塞下 Tab 进不了回调。折中：用 `tty.setcbreak()` 把终端设为 cbreak 模式，逐字符读 stdin，Tab(0x09) 触发切换，回车触发发送，其他字符累积成命令行。这样能实现 Tab 切换 + 行编辑。代码稍多但功能完整。
- **退出清理**：try/finally 恢复终端设置（`termios.tcsetattr` 还原）+ 关闭串口 + 停读线程。

### 线程模型

```
主线程: cbreak 读 stdin -> Tab切模式 / 回车发命令(ser.write + 打印TX>)
读线程: ser.read 循环 -> strip(可选) -> 打印 RX<
```
两线程都操作 stdout，用一把 `print_lock` 串行化 print，避免 TX/RX 交错撕裂。

## 改动清单

1. **新增 `ATS/tools/__init__.py`**（空）
2. **新增 `ATS/tools/serial_terminal.py`**：
   - `run_terminal(port, baudrate, strip_ansi=True)` 主函数
   - cbreak 终端 + 读线程 + TX/RX 着色打印 + Tab 切换 + 退出清理
3. **改 `ATS/main.py`**：
   - `parse_args` 加 `--terminal`（action store_true）和 `--raw`（action store_true，禁用 ANSI 剥离）
   - `main()` 开头（list-modules 之后、加载配置之前）加分支：`if args.terminal: return run_terminal_cmd(args)`
   - `run_terminal_cmd(args)`：解析 port/baudrate（复用 detect_port 逻辑或直接用配置），调 `run_terminal`
4. **记 devBugLog**：`20260813_<HHMM>_新增串口终端模式.md`，更新 README 索引

## 不改的部分

- `core/` 所有类（SerialConsole/runner/reporter 等）不动
- `modules/` 不动
- 现有测试流程不受影响（--terminal 是独立分支，早返回）

## 验证

1. `python3 -m ATS.main --terminal --help` 确认参数
2. 连板子跑 `python3 -m ATS.main --terminal`：
   - 自动探测到 /dev/ttyUSB0 @ 2000000
   - 敲 `help` 回车 -> 看到 TX> help（绿）+ RX< 板子返回的命令列表
   - 按 Tab -> 状态行切换 ANSI 模式
   - 敲 `exit` 或 Ctrl+C -> 干净退出，串口释放
3. 用它手动发 `rtmp_video_start rtmp://10.1.64.35/live/cam` 实时看板子反应（这正是用户要它做的 RTMP 调试）

## 风险

- **cbreak 模式兼容性**：Linux termios 标准接口，本机 Linux 5.15 OK。Ctrl+C 在 cbreak 下需手动捕获 `\x03`。
- **读线程 print 与主线程 print 交错**：用 print_lock 串行化，且每条 print 一次性输出完整行。
- **板子返回无换行结尾**：RX< 打印时若数据无 `\n` 则不补换行，保持流式；遇 `\n` 才换行。避免每个 read 调用都换行导致输出碎片化。
