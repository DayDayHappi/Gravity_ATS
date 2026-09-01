# 当前状态（Current Status）

## Current Version

分支 `new_arch`，Scenario 层重构完成（4 个提交）+ 20260824 改动（normal 移除重复 ftp task、修复 no-interactive-wifi 断链、WiFi 职责重划 ADR-008）+ 20260825/26 改动（ADR-010 PreviewManager、photo/video 判据修复、新增 stress_traverse_photo_mode 场景）+ 20260827 改动（video 启动判据加 f_index 兜底 + 失败清理、录像前暂时取消 cam_set），**均尚未真机验证**。

20260828 改动（commit `177976c`）：`stress_traverse_photo_mode` 参数调为冒烟值（loop 200 / photo repeat 1 / video 20s / rtmp 20s）+ WiFi 默认值改 `ftp_test_2_4G`；场景注释与参数脱钩已完成（commit `199ad95`，纯注释）。

20260831 改动（commit `0a43ac4`）：日志目录按「场景/日期/运行时间戳」三级分层（所有场景日志统一 `logs/<场景>/<日期>/<run_ts>/`，去掉中间冗余 logs 层；报告也按天分；problem 记录归入 `logs/<场景>/problem/`），**待真机验证**。

20260831 改动（devlog `20260831_1419`/`20260831_1753`）：新增独立 `download` 场景+模块（仅从板端 FTP 下载、不做测试，配合纯录像场景手动下载）+ 修复 download 完整性校验（`ftp_client.download` 远端大小未知不静默成功）+ 逐文件下载日志，**待真机验证**。

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
- base.py docstring 修正，对齐 ADR-009（「拓扑排序」旧语义 → 「运行时 fail-fast」）
- 仓库只跟踪 ATS + tools + docs
- ADR-010 PreviewManager 单例播放器源码已实施（ffplay 从 rtmp 模块剥离至驱动层）
- photo 判据修复：`Save Photo Successful` → `Capture completed successfully.` + 路径从 `r.clean` 累积缓冲扫描（真机验证通过）
- video 判据修复：`Save Video Successful` → `Video recording completed successfully.` + 路径从 `r.clean` 累积缓冲扫描（与 photo 同类的对称 bug，离线验证通过，待真机）
- 新增场景 `stress_traverse_photo_mode.yaml`（photo task 用 `override.photo_modes` 遍历全部拍照模式压测；`hdr` 模式名待真机核实 TODO-CONFIRM）
- video 启动判据加 f_index 兜底：`Record Start` → `Record Start|f_index\s*=`，失败分支补发 `dfs_video_stop` 清理（固件偶发漏打 Record Start 但编码在跑，devlog `20260827_0721`）
- video 录像前暂时取消 `cam_set`（`if False:` 跳过 + `TODO-TEMP-DISABLE-CAM_SET` 标记，后续恢复，devlog `20260827_0739`）
- 日志目录按「场景/日期/运行时间戳」三级分层（devlog `20260831_1032`）：所有场景日志统一 `logs/<场景>/<日期>/<run_ts>/`，报告也按天分，problem 记录归入 `logs/<场景>/problem/`
- 新增独立 `download` 场景+模块（devlog `20260831_1419`）：仅从板端 FTP 下载、不做测试，`downloads/` 加入 .gitignore
- 修复 download 完整性校验 + 逐文件日志（devlog `20260831_1753`）：`ftp_client.download` 远端大小未知不静默成功（重查兜底+可疑失败），download 逐文件成功/失败日志带两端大小

## Working On

- **待真机验证**：Scenario 层重构 + 第四次交接 4 项改动 + 20260824 改动 + ADR-010（20260825 源码已实施）+ 20260826 改动（video 判据修复 + stress_traverse_photo_mode 场景）+ 20260827 改动（video 启动判据 f_index 兜底 + 录像前取消 cam_set）+ 20260831 改动（日志目录三级分层 + download 场景/模块 + 下载完整性修复）全部未跑真机。
- **临时禁用待恢复**：`video.py` 录像前 `cam_set` 已用 `if False:` 跳过（`TODO-TEMP-DISABLE-CAM_SET`），真机验证后需按标记恢复。

## Known Issues

固件 bug 与文档过时点见 [known_issue.md](known_issue.md)。
