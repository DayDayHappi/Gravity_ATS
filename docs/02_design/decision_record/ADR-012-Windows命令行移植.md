# ADR-012：Windows / Ubuntu 共用命令行实现

日期：2026-09-16。状态：源码实施并完成 Debian Linux 自动化验证；Windows 原生与两平台 EVB 验收待完成。

## Context

基线是 `all_source(8).txt`，生成于 2026-09-16 11:06:04，收录 ATS、docs 共166个文件。
用户批准先迁移无 UI 的命令行，不引入 Qt、EXE 打包、多 EVB，不改拍照录像下载时机和 H.265 算法。
基线中的 Linux 串口枚举、termios 键盘、Bash 播放器及未贯穿的 config-dir 阻碍原生 Windows 使用。

## Decision

保留 `ScenarioManager → TestRunner → Module → Driver`、协议集中化及同一套 YAML。
新增 `ATS/platform/`，不复制 Windows 专用业务模块。

| 文件 | 职责 |
|---|---|
| ports.py | pySerial 枚举；USB优先、自然排序；自动探测排除蓝牙；显式端口不受此过滤限制 |
| console_input.py | Windows msvcrt / POSIX termios；上下文退出还原键盘；POSIX 增量解码处理粘贴 |
| tools.py | 平台正确的工具、工程根相对路径、实际 -version 校验；显式非默认路径失败不静默换工具 |
| processes.py | argv直接启动及超时、中断后的直接子进程回收；不按进程名杀进程 |

`--config-dir` 由入口传至 Context、Runner、FTP/预览准备动作和依赖检查。
模块 runtime override 在 setup 前合并，仍沿用模块自己的合并规则。CLI 嵌套覆盖保留未覆盖字段。
`--no-preview` 仅覆盖本次预览；`--no-problem-prompt` 仅关闭末尾问题记录；`--input-dir` 仅控制完整性检测输入。
独立 `video_integrity` 不要求 pySerial、板子或网络；涉及板端动作的场景仍检查 pySerial。

PreviewManager 保留 start/stop/restart/is_running 和低延迟 ffplay 参数。
**有意改变的启动细节**：两平台均由 Python 监督直接启动 ffplay，不再额外打开 gnome-terminal/xterm/Bash。
画面窗口仍可选，断流退出后自动重连，诊断记录到本次 run 的 preview.log。

Runner finally 清理、Manager 保留结果、中断返回130；FTP半初始化连接在异常时关闭。
停止录像/推流未收到应答时记录警告，不宣称板端一定停止。
nginx 仍是外部服务，ATS 不启动、不安装、不结束它；就绪检查仍针对本机127.0.0.1:1935。

## Boundaries and non-changes

- 板端 `/emmc/...` 和所有 `*_commands.py` 不因主机是 Windows 而改动。
- 原有8个正式场景与8个模块 YAML、system.yaml 均保留原样；只新增2个小规模 smoke 场景。
- 保留32B分片、同步哨兵、异步正则、2Mbps默认、主动FTP、每次录像下载和TT ERROR标注。
- H.265 的判据、POC推算、manifest选择算法未修订；本次验证不等价于证明其全部诊断精度。
- `preview_required` 仍只影响预览异常日志级别，不新增硬性失败判据。
- RTMP正常停止应答失败会写日志/结果详情，最终主判据仍为ffprobe和heartbeat；未改成严格stop-ack判FAIL。
- 原有“部分FTP辅助验证失败仍PASS”行为保留，真机验收必须检查文件实际下载，不能仅看PASS。

## Alternatives

复制 Windows Module/Runner 会产生测试判据漂移，因此不采用。
要求 WSL/Bash 可减小代码改动，但不符合本轮原生Windows CLI目标，因此不作为默认部署。
使用另一台Ubuntu作RTMP服务需要远端就绪检查扩展，本轮未实现；不能只改stream_url冒充独立Windows部署。

## Verification

见 `../../04_testing/windows_cli_acceptance.md`。当前证据是Linux自动化、Windows分支模拟及真实Linux FFmpeg；不是Windows真机证据。
