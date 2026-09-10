# 当前状态（Current Status）

## Current Version

分支 `new_arch`，Scenario 层重构完成（4 个提交）+ 20260824 改动（normal 移除重复 ftp task、修复 no-interactive-wifi 断链、WiFi 职责重划 ADR-008）+ 20260825/26 改动（ADR-010 PreviewManager、photo/video 判据修复、新增 stress_traverse_photo_mode 场景）+ 20260827 改动（video 启动判据加 f_index 兜底 + 失败清理、录像前暂时取消 cam_set），**均尚未真机验证**。

20260828 改动（commit `177976c`）：`stress_traverse_photo_mode` 参数调为冒烟值（loop 200 / photo repeat 1 / video 20s / rtmp 20s）+ WiFi 默认值改 `ftp_test_2_4G`；场景注释与参数脱钩已完成（commit `199ad95`，纯注释）。

20260831 改动（commit `0a43ac4`）：日志目录按「场景/日期/运行时间戳」三级分层（所有场景日志统一 `logs/<场景>/<日期>/<run_ts>/`，去掉中间冗余 logs 层；报告也按天分；problem 记录归入 `logs/<场景>/problem/`），**待真机验证**。

20260907/08 改动（commit `a9bf449` + `519e805`）：video 录像前恢复 `cam_set`（撤销 20260827 临时禁用）；RTMP heartbeat 正则放宽为裸 `f_index` 匹配（适配固件日志格式 `[RTMP] f_index` → `I/App Rtmp: f_index`，`heartbeat_timeout` 60→40）；stress_traverse_photo_mode 场景 video 与 rtmp 之间接入 `video_integrity`（录像→检测闭环），video/rtmp 时长调为 66s；WiFi 默认改 `sw_test_24g`，**均待真机验证**。

20260909 改动（commit `d7cee21`「增加 11 种录像 size 遍历」）：新增 `ATS/drivers/video_commands.py`（完整录像命令表，11 种 size 组合 ID + 宽高/方向元数据 + 禁用校验）；`video.py` 改为查表下发完整命令、不再拼 `cam_set video {resolution}`，`video_resolution` 从裸档位改为完整组合 ID（如 `3k_2`，裸档位会 ERROR）；新增场景 `video_size_traverse.yaml`（11 种 size 遍历）；既有 3k 场景 video override 由 `"3k"` 迁移为 `"3k_2"`，**待真机验证**。24 项离线回归通过（devlog `20260909_录像size显式命令与遍历`）。

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
- video 录像前暂时取消 `cam_set`（`if False:` 跳过 + `TODO-TEMP-DISABLE-CAM_SET` 标记，20260907 已恢复，devlog `20260827_0739`）
- 日志目录按「场景/日期/运行时间戳」三级分层（devlog `20260831_1032`）：所有场景日志统一 `logs/<场景>/<日期>/<run_ts>/`，报告也按天分，problem 记录归入 `logs/<场景>/problem/`
- video 录像前恢复 `cam_set`（撤销 `if False:` 跳过 + `TODO-TEMP-DISABLE-CAM_SET` 标记，devlog `20260907_1848`）
- RTMP heartbeat 正则放宽为裸 `f_index` 匹配 + `heartbeat_timeout` 40s（适配固件日志格式变更，devlog `20260907_2007`）
- stress_traverse_photo_mode 场景接入 `video_integrity`（video→检测闭环，devlog `20260907_2039`）
- 新增 `drivers/video_commands.py`：录像 size 完整命令表（11 种组合 ID，映射用户手测，`480p_1` 禁用）；`video.py` 改查表下发、拒绝裸档位（devlog `20260909_录像size显式命令与遍历`）
- 新增场景 `video_size_traverse.yaml`（11 种 size 遍历 + 统一 H265 检测 + photo 遍历 + RTMP 推流；接入 video_integrity 见 devlog `20260909_1940`）

## Working On

- **待真机验证**：Scenario 层重构 + 第四次交接 4 项改动 + 20260824 改动 + ADR-010（20260825 源码已实施）+ 20260826 改动（video 判据修复 + stress_traverse_photo_mode 场景）+ 20260827 改动（video 启动判据 f_index 兜底）+ 20260831 改动（日志目录三级分层）+ 20260907/08 改动（cam_set 恢复 + RTMP heartbeat 裸 f_index + video_integrity 接线）+ 20260909 改动（video_commands 命令表 + video_size_traverse 场景 + 3k 场景迁移 3k_2 + video_size_traverse 接入检测）全部未跑真机。

## 固件行为快照（当前版本，未来可能变动）

> 2026-09-09（commit `d7cee21`）起，录像 size 改为**完整组合 ID** 下发，权威映射与命令
> 定义统一在 `ATS/drivers/video_commands.py`（11 种组合，含宽高/方向/禁用校验）。
> 下方历史表（2026-09-08，裸档位体系）已过时，仅作历史留档。

历史裸档位实测（ffprobe 实测落盘文件，2026-09-08）：

| 触发方式 | 板端回显 w*h | 实际落盘分辨率 | 方向 |
|---------|-------------|--------------|------|
| 发送 `cam_set video 1080p` | `w(1920) * h(1080)` | **1920 × 1080** | 横屏 |
| 不发送 `cam_set`，直接录像 | — | **1296 × 2304** | 竖屏（固件默认） |
| 发送 `cam_set video 3k` | `w(2520) * h(1890)` | **2268 × 3024** | 竖屏（sensor 旋转后） |

> 注：历史 devlog `20260817_0203` 中「1080p = 1296×2304」「只支持 4k/1080p 两档」为过时/错误认知（见 known_issue.md）。固件升级后此表可能失效，需以真机实测为准。

## Known Issues

固件 bug 与文档过时点见 [known_issue.md](known_issue.md)。
