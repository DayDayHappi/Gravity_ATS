# 当前状态（Current Status）

## Current Version

分支 `new_arch`，Scenario 层重构完成（4 个提交）+ 20260824 改动（normal 移除重复 ftp task、修复 no-interactive-wifi 断链、WiFi 职责重划 ADR-008）+ 20260825/26 改动（ADR-010 PreviewManager、photo/video 判据修复、新增 stress_traverse_photo_mode 场景）+ 20260827 改动（video 启动判据加 f_index 兜底 + 失败清理、录像前暂时取消 cam_set），**均尚未真机验证**。

20260828 改动（commit `177976c`）：`stress_traverse_photo_mode` 参数调为冒烟值（loop 200 / photo repeat 1 / video 20s / rtmp 20s）+ WiFi 默认值改 `ftp_test_2_4G`；场景注释与参数脱钩已完成（commit `199ad95`，纯注释）。

20260831 改动（commit `0a43ac4`）：日志目录按「场景/日期/运行时间戳」三级分层（所有场景日志统一 `logs/<场景>/<日期>/<run_ts>/`，去掉中间冗余 logs 层；报告也按天分；problem 记录归入 `logs/<场景>/problem/`），**待真机验证**。

20260907/08 改动（commit `a9bf449` + `519e805`）：video 录像前恢复 `cam_set`（撤销 20260827 临时禁用）；RTMP heartbeat 正则放宽为裸 `f_index` 匹配（适配固件日志格式 `[RTMP] f_index` → `I/App Rtmp: f_index`，`heartbeat_timeout` 60→40）；stress_traverse_photo_mode 场景 video 与 rtmp 之间接入 `video_integrity`（录像→检测闭环），video/rtmp 时长调为 66s；WiFi 默认改 `sw_test_24g`，**均待真机验证**。

20260909 改动（commit `d7cee21`「增加 11 种录像 size 遍历」）：新增 `ATS/drivers/video_commands.py`（完整录像命令表，11 种 size 组合 ID + 宽高/方向元数据 + 禁用校验）；`video.py` 改为查表下发完整命令、不再拼 `cam_set video {resolution}`，`video_resolution` 从裸档位改为完整组合 ID（如 `3k_2`，裸档位会 ERROR）；新增场景 `video_size_traverse.yaml`（11 种 size 遍历）；既有 3k 场景 video override 由 `"3k"` 迁移为 `"3k_2"`，**待真机验证**。24 项离线回归通过（devlog `20260909_录像size显式命令与遍历`）。

20260917 改动（devlog `20260917_1620` + `20260917_1634`）：photo 单拍新增 3 个分辨率变体 —— `photo_commands.py` 的 `PHOTO_MODES` 枚举 +3 条含空格模式名（`single 1080p/720p/480p`），`stress.yaml` photo task `override.photo_modes` 7→10 项；命令模板 `str.format` 天然支持含空格模式名，`photo.py` 零改动；随后 `stress.yaml` photo task 1→10 拆分（各单模式 + `repeat:1`，搭骨架支持每模式独立 repeat，纯配置零源码改动）。已核实 report 消费方对含空格 `name` 无解析副作用，**待真机核实固件是否接受 `cam_set photo single <res>` 三 token 写法**（TODO-CONFIRM）。

20260917 改动（devlog `20260917_1659`）：video 新增 480p_1 组合 —— `video_commands.py` 补 profile（640×480 横屏，TODO-CONFIRM）+ 解除禁用，`stress.yaml` 插 480p_1 task，`video_size_traverse.yaml` 仅改注释；`video.py` 零改动。**待真机 ffprobe 校准预期宽高**。另用户手改 stress.yaml 全部 video task 参数为 `repeat:1` + `duration:20`（原 `sd1080p_0/1` repeat=10、duration=10），属手动参数调整，随本次一并留痕。

20260918 改动（devlog `20260918_0010` + `20260918_0030` + `20260918_0100`）：检测关键字符串集中化（ADR-014）—— 检测串定义唯一来源 `drivers/detect_strings.py`（DetectString + DETECT_STRINGS），`tt_error_monitor.py`→`string_hit_monitor.py`（TTErrorMonitor→StringHitMonitor 泛化），video/rtmp 改读 `detect_strings` 配置、命中只收集不判 FAIL；新增检测串 `imu fmq overflow f=`（纯字面串、`=` 后数字不校验、大小写敏感）；video 新增录像组合 `4k_0`（`cam_set video 4k 0`，预期 size 占位 `0x0` 待真机 ffprobe 校准，不接场景）。均**待真机**。

20260920 改动（devlog `20260920_1053`）：修复 `serial_console.exec_sync` 环形缓冲滚满后快照定位失效致 cam_set 误判（BUG-005）。方案 A：快照定位从「字符串前缀」改「单调递增序号游标」（`deque(str)`→`deque(tuple[int,str])` + `_snapshot_seq`/`_buffer_text_since`，`_wait_pattern`/`_wait_regex`/`exec_sync`/`exec_async`/`wait_for_ready` 改用游标）；并收窄 `_ERROR_RE` 排除 `invalid[, ]use default` 相机正常 fallback。对外 API 不变，离线模拟滚满场景 PASS，**待真机 stress 26 轮验证**。

## Current Architecture

场景驱动的分层执行模型：config（三层）→ ScenarioManager（编排）→ Runner（调度）→ Module（动作）→ Driver（通信）。
WiFi 属 prepare 环境准备（wifi_connect 收敛器 + wifi_check 状态检测器），不作 task（ADR-008 已实施）。
ADR-016 引入应用服务层（Application Service）：BoardHealthMonitor / RecoveryCoordinator / RecoveryBackend，跨模块系统级协调，已实施（devlog `20260921_1820`），三轮验收闭环修复（devlog `20260922_1330`/`1404`/`1423`）+ 冷启动/串口生命周期修复（devlog `20260922_1603`）+ BUG-006 修复（devlog `20260923_1110`）完成，恢复链真机验证通过（2026-09-23）。

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
- video 新增 480p_1 组合：`video_commands.py` 补 `480p_1` profile（640×480 横屏，TODO-CONFIRM）+ 从 `BLOCKED_VIDEO_PROFILES` 解除禁用（保留空常量防 NameError）；`stress.yaml` 480p_0/480p_2 之间插 480p_1 task；`video_size_traverse.yaml` 仅修正过时禁用注释（devlog `20260917_1659`，video.py 零改动，待真机 ffprobe 校准预期宽高）
- 新增场景 `video_size_traverse.yaml`（11 种 size 遍历 + 统一 H265 检测 + photo 遍历 + RTMP 推流；接入 video_integrity 见 devlog `20260909_1940`）
- photo 单拍新增 3 个分辨率变体：`PHOTO_MODES` 枚举 +3 条（`single 1080p/720p/480p`），`stress.yaml` photo task `override.photo_modes` 7→10 项（devlog `20260917_1620`，photo.py 零改动，待真机）
- `stress.yaml` photo task 1→10 拆分（各单模式 + `repeat:1`，搭骨架支持每模式独立 repeat；devlog `20260917_1634`，纯配置，待真机）
- 检测关键字符串集中化（ADR-014）：`drivers/detect_strings.py` 唯一来源 + `string_hit_monitor.py` 泛化 + video/rtmp 改读 `detect_strings`（devlog `20260918_0010`，待真机）
- 新增检测串 `imu fmq overflow f=`：`detect_strings.py` 追加 + video/rtmp.yaml 选择键加 `imu_fmq_overflow`（devlog `20260918_0030`，纯数据改动，待真机）
- video 新增录像组合 `4k_0`：`video_commands.py` 补 profile（`cam_set video 4k 0`，预期 size 占位 0x0 待真机 ffprobe 校准，不接场景；devlog `20260918_0100`）
- 板卡健康监测与可插拔恢复机制（ADR-016）已实施（devlog `20260921_1820`）：`ATS/application/`（board_health_monitor + recovery_coordinator + recovery_backends + runtime_control）+ `core/` 接线（context/logger/scenario/scenario_manager/runner/reporter/main）+ `config/modules/board_health.yaml`；**三轮验收闭环修复 + 冷启动/串口生命周期修复 + BUG-006 修复完成**（devlog `20260922_1330`/`1404`/`1423`/`1603` + `20260923_1110`）；37 个 unittest 全过；**恢复链真机验证通过**（2026-09-23：冷启动 + SUSPECTED 检测 + 完整 PowerCycle 恢复 + video 重跑）

## Working On

- **板卡健康监测与可插拔恢复机制（ADR-016，已实施·恢复链真机验证通过）**：Document Agent 2026-09-21 定稿，Code Agent 实施主体（devlog `20260921_1820`）+ 三轮验收闭环修复（devlog `20260922_1330`/`1404`/`1423`）+ 冷启动/串口生命周期修复（devlog `20260922_1603`）+ BUG-006 修复（devlog `20260923_1110`）。**2026-09-23 真机验证**：冷启动 ✓、SUSPECTED 检测+主动确认 ✓（TC-BH-003）、完整 PowerCycle 恢复链 ✓（拔电源 → UNRESPONSIVE → OFF/ON → serial_reconnect → board_ready → WiFi → FTP → retry_current_task，video 重跑）。**待续真机**：TC-BH-001/002、TC-RCV-002~005 边界用例 + `inactivity_timeout`/`reboot_delay` 校准。
- **待真机验证**：Scenario 层重构 + 第四次交接 4 项改动 + 20260824 改动 + ADR-010（20260825 源码已实施）+ 20260826 改动（video 判据修复 + stress_traverse_photo_mode 场景）+ 20260827 改动（video 启动判据 f_index 兜底）+ 20260831 改动（日志目录三级分层）+ 20260907/08 改动（cam_set 恢复 + RTMP heartbeat 裸 f_index + video_integrity 接线）+ 20260909 改动（video_commands 命令表 + video_size_traverse 场景 + 3k 场景迁移 3k_2 + video_size_traverse 接入检测）+ 20260917 改动（photo 单拍 3 个分辨率变体 + photo task 1→10 拆分）全部未跑真机。

## 固件行为快照（当前版本，未来可能变动）

> 2026-09-09（commit `d7cee21`）起，录像 size 改为**完整组合 ID** 下发，权威映射与命令
> 定义统一在 `ATS/drivers/video_commands.py`（当前 13 种组合，含宽高/方向/禁用校验；
> 其中 `4k_0` 预期 size 占位 0x0 待真机校准）。
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
