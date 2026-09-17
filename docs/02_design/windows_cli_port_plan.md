# Windows CLI Port Implementation Plan

> **For agentic workers:** 使用 executing-plans 按任务实施；每项先运行失败用例，再改源码，最后回归。当前方案已由用户在本会话批准。

**Goal:** 基于 all_source(8).txt 实现同一份源码在 Ubuntu / 原生 Windows 上运行无 Qt 的 ATS CLI。

**Architecture:** 保留 ScenarioManager → Runner → Module → Driver。主机端口枚举、键盘、工具定位、子进程收敛到 ATS/platform；板端命令和判据仍由现有 *_commands.py 维护。

**Tech Stack:** Python 标准库、pyserial、PyYAML、Jinja2；测试用 pytest；外部 ffmpeg/ffprobe/ffplay 和 nginx-rtmp 由部署者提供。

**Spec:** 本会话用户批准的“Windows / Ubuntu 双平台 CLI 移植方案”；实施边界见 ADR-012-Windows命令行移植.md。

## Global Constraints

- 基线生成时间 2026-09-16 11:06:04，166 个文件；快照仅收录 ATS、docs，不能假定根目录工具、依赖文件和旧测试已提供。
- 不引入 Qt、不做 UI/EXE、多 EVB、FTP 延后下载或 H.265 算法修改。
- 不修改正式 scenarios/*.yaml、现有 modules/*.yaml 及串口 *_commands.py 的协议值。
- 保留串口同步/异步语义、32B 分片、2 Mbps 默认、FTP 主动模式、TT ERROR 标注、H.265 去重。
- Windows 原生和 EVB 验证不能用 Linux 模拟测试替代；如实记录环境。
- 新依赖文件放 ATS/requirements-cli*.txt，新增测试放 tests/windows_cli，避免覆盖未收录的根依赖和旧测试。

## Task 1: 平台基础

Files: 新增 ATS/platform/{__init__,ports,console_input,tools,processes}.py；tests/windows_cli/test_platform.py。

Interfaces:
- ports.list_ports()：仅枚举元信息；ports.candidate_ports()：USB 优先、自然排序、排除蓝牙自动探测。
- console_input.KeyboardInput：with 生命周期，read(timeout) 返回字符/None/EOF空串。
- tools.project_root()/resolve_tool(name, preferred=None, root=None)：资源相对工程根，返回经 -version 验证的绝对可执行路径，失败 ToolError。
- processes.spawn()/run_capture()/terminate_process()：只管理本次直接创建的可执行子进程，无 shell、无全局按进程名终止。

- [x] 写用例：COM10/COM2 排序，Linux USB/ACM 保留，蓝牙不自动探测；显式路径不静默回退；Windows 默认选 .exe；真实超时子进程回收。
- [x] 运行 `python -m pytest tests/windows_cli/test_platform.py -q` 确认缺少新接口导致失败。
- [x] 实现上述接口，Windows 惰性导入 msvcrt，POSIX 惰性导入 termios/tty。
- [x] 重跑平台用例并记录结果。

## Task 2: 配置、CLI 与终端

Files: 修改 main.py、core/{scenario_manager,runner,serial_console}.py、modules/ftp.py、tools/serial_terminal.py；tests/windows_cli/test_cli.py。

- [x] 用例固定 `--config-dir` 必须贯穿 prepare/runner/依赖检查；setup 应看到 task.override；Ctrl+C 不丢已有结果。
- [x] 先运行失败用例。
- [x] config_dir 经 Context + Runner 参数传递；保留模块自己的合并规则。
- [x] 新增 --no-preview、--no-problem-prompt、--input-dir、--list-ports，不把 --no-interactive-wifi 变成全局无人值守开关。
- [x] `--terminal` 复用 KeyboardInput；串口设备打开失败、非TTY及断开时都释放资源。
- [x] Manager 保存结果引用；Runner 在 finally 调 teardown；中断输出部分报告并返回130。
- [x] 重跑 CLI 与终端用例。

## Task 3: 工具与进程接入

Files: 修改 drivers/{rtmp_receiver,h265_validator,preview_manager,rtmp_server}.py、modules/{rtmp,video}.py；tests/windows_cli/test_lifecycle.py。

- [x] 写用例验证 ffprobe 参数及超时、H265 子进程 Ctrl+C 回收、预览单实例/重连/停止。
- [x] 先运行失败用例。
- [x] 所有工具使用统一定位和生命周期；FFmpeg 原有诊断 argv 不改算法。
- [x] PreviewManager 用 Python 监督直接启动 ffplay，去除 Bash/终端模拟器依赖，两平台一致。
- [x] RTMP run 的异常路径补停流，清理响应失败明确记录，nginx 仍是外部服务。
- [x] 重跑生命周期及协议回归用例。

## Task 4: 部署、冒烟、交付

Files: 新增跨平台 cli_smoke_capture/cli_smoke_rtmp 场景；ATS/requirements-cli*.txt；docs/05_handoff/windows_cli_使用指南.md；docs/04_testing/windows_cli_acceptance.md。

- [x] 保留所有正式场景不动；冒烟录像后检测无输入必须失败，避免下载缺失被忽略。
- [x] 使用真实系统 FFmpeg 生成正常 H265 样本并运行完整独立检测CLI；异常样本必须非PASS。
- [x] 全部新增测试、AST/compileall、CLI导入检查与文件差异审计。
- [x] 交付单一增量ZIP，附校验/备份安装器、修改清单及验证日志；不包含旧文件/二进制/虚拟环境。
- [x] 对干净基线实际应用ZIP并复测，测试安装冲突拒绝与重复安装幂等。

## 真机后续验收（未在本环境执行）

- [ ] Windows原生 COM / 2Mbps / 主动FTP / nginx-rtmp / ffplay。
- [ ] Ubuntu现有EVB场景回归。

打包与安装验证的最终输出见验收记录和包内validation日志；本计划不替代验证证据。
