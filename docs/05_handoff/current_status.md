# 当前状态（Current Status）

## Current Version

分支 `new_arch`，Scenario 层重构完成（4 个提交），**尚未真机验证**。

## Current Architecture

场景驱动的分层执行模型：config（三层）→ ScenarioManager（编排）→ Runner（调度）→ Module（动作）→ Driver（通信）。

## Completed

- 串口通信 + 哨兵机制 + 自动探测 + 波特率回退
- 8 模块测试链路此前真机全部 PASS
- RTMP 推流打通（nginx-rtmp + 内置 ffmpeg + ffprobe + heartbeat）
- FTP 会话策略 + Scenario 层重构 + 场景隔离 + ftp_ready 幂等
- 仓库只跟踪 ATS + tools

## Working On

- **待真机验证**：Scenario 层重构 + 第四次交接 4 项改动（TX/RX 时间戳、exec_async 去哨兵、RTMP heartbeat、测试结束询问）全部未跑真机。
- **P0**：stress/aging 场景 WiFi 前置缺失（见 next_step.md）。

## Known Issues

固件 bug 与文档过时点见 [known_issue.md](known_issue.md)。
