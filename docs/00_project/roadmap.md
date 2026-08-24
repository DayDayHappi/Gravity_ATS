# 路线图（Roadmap）

> 只记录「已完成 / 进行中 / 计划中」，不记录历史过程。

## Completed（已完成）

- 串口通信 + 哨兵机制 + 自动探测 + 波特率回退
- 8 模块测试链路（wifi/emmc/ftp/photo/video/rtmp）此前真机全部 PASS
- RTMP 推流打通（nginx-rtmp + 内置 ffmpeg + ffprobe 实时探测 + heartbeat）
- 内置 ffmpeg/ffprobe/ffplay（离线可用）
- FTP 会话策略（只发一次 / 冷启动 / 重建连接 / 主动模式）
- Scenario 层重构（配置三层拆分 + Task/repeat/loop + 场景隔离）
- 修复 `--no-interactive-wifi` 断链（原 P0-1，方向 A）
- normal 场景移除重复 ftp task
- WiFi 职责重划（ADR-008）源码已实施：normal tasks = emmc/photo/video/rtmp
- depends 字段清理（ADR-009）源码已实施：6 个模块死依赖清空
- 仓库只跟踪 ATS + tools + docs

## Current（进行中）

- **未完成**：Scenario 层重构 + 第四次交接 4 项改动 + 20260824 改动全部待真机验证
- **待 Code Agent**：base.py docstring 过时（「拓扑排序」旧语义）

## Planned（计划中）

- 真机验证 normal + stress 场景
- loop 语义增强（支持循环外一次性前置任务）
- RTMP 类型2 网络异常覆盖（周期 ffprobe 复探）
- 文档 CLI 过时点同步（`--scenario` 主入口）
