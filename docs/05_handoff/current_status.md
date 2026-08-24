# 当前状态（Current Status）

## Current Version

分支 `new_arch`，Scenario 层重构完成（4 个提交）+ 20260824 改动（normal 移除重复 ftp task、修复 no-interactive-wifi 断链、WiFi 职责重划 ADR-008 已实施），**均尚未真机验证**。

## Current Architecture

场景驱动的分层执行模型：config（三层）→ ScenarioManager（编排）→ Runner（调度）→ Module（动作）→ Driver（通信）。
WiFi 属 prepare 环境准备（wifi_connect 收敛器 + wifi_check 状态检测器），不作 task（ADR-008 已实施）。

## Completed

- 串口通信 + 哨兵机制 + 自动探测 + 波特率回退
- 8 模块测试链路此前真机全部 PASS
- RTMP 推流打通（nginx-rtmp + 内置 ffmpeg + ffprobe + heartbeat）
- FTP 会话策略 + Scenario 层重构 + 场景隔离 + ftp_ready 幂等
- 修复 `--no-interactive-wifi` 断链（原 P0-1，方向 A，离线单测通过）
- normal 场景移除重复 ftp task（FTP 由 prepare.ftp_ready 保证）
- WiFi 职责重划（ADR-008）源码已实施：normal tasks = emmc/photo/video/rtmp
- depends 字段清理（ADR-009）源码已实施：6 个模块死依赖清空
- 仓库只跟踪 ATS + tools + docs

## Working On

- **待真机验证**：Scenario 层重构 + 第四次交接 4 项改动 + 20260824 改动全部未跑真机。
- **待 Code Agent**：base.py docstring 过时（「拓扑排序」旧语义），见 next_step.md P1。

## Known Issues

固件 bug 与文档过时点见 [known_issue.md](known_issue.md)。
