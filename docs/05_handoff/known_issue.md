# 已知问题（Known Issues）

## 固件 bug（脚本无法根治，勿当脚本 bug 改）

| Issue | Impact | Workaround | Status |
|-------|--------|-----------|--------|
| ImuThread 崩溃 → ffplay 画面卡住 | 连续录 180s 视频 + 立即推流 ~3min 后 | 已整理 `RV_Backtrace` 线索转固件工程师；脚本靠 heartbeat 提前判 FAIL | 待固件修复 |
| FTP 崩溃循环 `service go wrong` 刷屏 | 拍照/录像后 | 只发一次 ftp_server + ensure_ftp 每次下载前重建连接 | 沿用 workaround |
| RTMP 命令卡死板子（串口零响应） | 未联网/状态异常时发 `rtmp_video_start` | 确保 WiFi 已连 + 摄像头就绪再发；卡死需物理重启 | 待固件修复 |
| RTMP 发送线程启动调度延迟 | 前一重负载结束到 RTMP 冷却间隔太短 | 前几十帧积压、首 IDR 延时大，属固件线程调度问题 | 待固件修复 |
| 关键帧(IDR)稀疏 | 1080p 编码慢 + FTP 刷屏抢 CPU | 探测超时放宽（-rw_timeout 15s），别用 640×480 经验值套大分辨率 | 待固件优化 |
| eMMC 文件系统大量照片写入后失效 + 固件「假成功」标志 | stress_traverse 压测约第 44 张起 `Image_*.jpg write failed errno=0`（open 成功 write 失败）→ `write open failed errno=-2`（ENOENT，目录建不出，累计 1353 条，不可恢复）；jpg 未落盘但固件仍打印 `Save Photo Successful`/`Capture completed successfully.`，脚本主判据误判 PASS | 转固件工程师定位（疑似 eMMC 目录/inode 超限、写缓冲泄漏、文件系统损坏）；脚本侧「未列出 jpg 辅助验证」应视为需警惕信号而非完全忽略 | 待固件修复 |
| `Record Start` 偶发漏打（摄像头资源退化） | 连续压测后期 `dfs_video_start` 后无 `Gravity_XR Record Start`，但 `f_index` 持续增长（编码在跑） | `f_index` 才是编码真实心跳（每 90 帧一次，第一次 `f_index=0` 第二次 `=90`），video 启动判据应加 `f_index` 而非只看 `Record Start`；详见 next_step.md 紧急待办 | 待脚本侧修复（Code Agent） |
| RTMP heartbeat 日志格式变更 | 固件推流心跳由 `[RTMP] f_index = N`（8 月日志）变为 `I/App Rtmp: f_index = N`（9 月日志），`RTMPMonitor` 正则 `\[RTMP\]\s+f_index` 失配 → 推流正常也在 60s 后误判 TIMEOUT、提前 `rtmp_video_stop` 判 FAIL（实测 20260907 连续 3 轮，串口 `I/App Rtmp: f_index` 共 88 条、`[RTMP] f_index` 0 条） | 已放宽 monitor 心跳正则为裸 `f_index` 匹配（rtmp 推流窗口内串口仅有 Rtmp 一种 f_index；前缀会被串口分块截断故不宜锚定），devlog `20260907_2007` | **已修复（待真机验证）** |

排查先 grep serial.log 的 `RV_Backtrace` / `ImuThread` / `discontinuous frame` / `interp not finish in sof` / `write failed errno` / `write open failed`。

## 脚本侧已知问题（待 Code Agent 修复，非固件 bug）

| Issue | Impact | 状态 |
|-------|--------|------|
| `exec_sync` 长时压测误判：环形缓冲滚满后 `full.startswith(snapshot)` 失效 → `new=full` 混入 RTMP 残留日志，`_ERROR_RE` 命中固件正常调试串 `preset capCfg ... invalid, use default`（780 条）→ `cam_set photo/video` 被误判 FAIL，photo 提前 return 不再发 `dfs_capture_start` | stress 压测约第 26 轮起 photo/video 全 FAIL（真机 2026-09-18） | **已修复（方案 A 序号游标，devlog `20260920_1053`，待真机）** |
| ADR-016 运行时闭环 7 P0 + 6 P1（Monitor 非持续监测、cooperative cancellation 未闭环、abort 只退当前 cycle、recovery_history 被 cleanup 清空、board_ready 命中旧缓冲、monitor-only 无 FAIL/abort 语义等） | 曾不建议作为 stress/aging 自动恢复正式版本 | **已修复**（devlog `20260922_1330`，13 项全过） |
| ADR-016 第二轮验收 2 P0 + 2 P1 + 1 P2 + QA-GAP-01（恢复失败无 framework FAIL、Policy 未完整 fail-closed、生命周期接线未前置校验、mock 未固化、watchdog stop 不立即唤醒、无 recovery_validation 场景） | 恢复失败可能被 CI 误判通过等 | **已修复**（`board_recovery ERROR`、`validate()` policy 校验、`_validate_scenario_runtime_contract`、`recovery_validation.yaml`、23 个 unittest 均已落地） |
| ADR-016 第三轮验收 3 软件点 + 1 QA（`after_recovery=continue` 与 Runner 冲突、PowerCycle 未严格验证 OFF/ON 回帧、`--dry-run` 不执行契约校验、tests/ 被 `.gitignore` 忽略） | 恢复成功可能被误判失败；板子未真正断电却被判恢复成功；dry-run 假通过；测试未入 git | **已修复**（devlog `20260922_1423`，commit `4fa40d1`：Runner 增 `continue` 分支、`reboot_checked()`、`validate_scenario()` 公开入口、`.gitignore` 放行 tests；30 unittest 全过） |
| ADR-016 NEW-P0-05 冷启动依赖顺序反转（prepare 为 `serial_init → power_switch_init`，EVB 初始断电时 serial_init 必失败、PowerSwitch 永远得不到上电机会，bootstrap deadlock） | `recovery_validation` 无法在 EVB 初始断电时启动，必须先人工上电 | **已修复**（devlog `20260922_1603`：prepare 改 `power_switch_init → serial_init` + serial 上电后 bounded wait + recovery 场景 power_switch fail-closed） |
| ADR-016 NEW-P0-06 PowerCycle 后 EVB 串口未重建（复用旧 `SerialConsole._ser`，UART 掉电重枚举后句柄失效） | 运行中恢复时 fresh-ready 收不到新 RX | **已修复**（devlog `20260922_1603`：`SerialConsole.reconnect()` 保持对象身份 + 新增 `serial_reconnect` 恢复 action + restore 顺序 `serial_reconnect → board_ready`） |
| ADR-016 BUG-006：`serial_reconnect` 端口探测与旧串口句柄冲突（先探测再 reconnect，探测时旧 reader 仍持原端口 → pyserial `multiple access on port` → 30s 超时误判「未重新枚举」） | 真机拔电源后 PowerCycle 成功但 restore 失败 → abort，task 未重跑 | **已修复 + 真机验证通过**（devlog `20260923_1110`：探测前先 close 旧句柄；端口未消失时直接 reconnect 原端口；日志 `20260923_111113` 完整恢复链走通 + video 重跑） |

## ADR-016 真机门槛（待真机确认）

- **UART 是否掉电重枚举**：冷启动/运行中 PowerCycle 后 EVB UART 是否消失并 USB 重枚举，需真机确认（`dmesg -w`/`udevadm monitor`）。**但无论结果如何，`SerialConsole.reconnect()` 都已实现且结构上必需**：若不重枚举则退化为幂等 reopen，若重枚举则是刚需。真机还需校准 `power_on_detect_timeout`/`reboot_delay`/serial reconnect timeout，禁止凭经验固定值。

## ADR-016 能力边界（设计内限制，非 bug）

- **只能识别「串口静默型整板无响应」**（超过 `inactivity_timeout` 无任何 RX：板子彻底安静、CPU hang 后不再打印、掉电）。若业务线程已死、msh 无法工作但后台错误日志持续刷串口，`last_rx` 会一直更新，Monitor 不会进入 SUSPECTED。本轮不扩大成复杂多源 watchdog。
- 未来扩展方向：Task 业务 timeout → 触发 board health probe → shell 也不响应 → 升级 UNRESPONSIVE，覆盖「串口仍刷日志但控制链路已死」的故障。

## 文档过时点（后续顺手修）

| 位置 | 现象 |
|------|------|
| `config/system.yaml` | WiFi 默认值已再次变更为 `sw_test_24g`/`12345678`（commit `a9bf449`，历史候选 SW-test-2.4G/ftp_hw_2_4g/G-Demo/ftp_test_2_4G 已注释）；但 `ATS/README.md`、`archive/使用手册`、`archive/00_阅读导航` 仍写 `G-Demo`/`Gdemo@123` |
| `devlog 20260817_0203` L24/L37 | 写「1080p = 1296×2304」「板子分辨率只支持 4k/1080p 两档」——**错误**。ffprobe 实测（2026-09-08）：`cam_set video 1080p` → 1920×1080（横屏）；不发 cam_set 直接录 → 1296×2304（竖屏，固件默认）；`cam_set video 3k` → 2268×3024（竖屏）。1296×2304 是不发 cam_set 时的固件默认，非 1080p 档。正确映射见 current_status.md「固件行为快照」 |
| `modules/__init__.py` | 注释说 wifi 注册 scan/join，实际还注册了 `wifi_check` |
| `ATS/README.md` | 第 5 节哨兵机制仍写 `cmd; echo <TOKEN>`（旧写法），实际已改换行分隔 |
| 使用手册 | CLI 命令（`--modules`/`--skip`/`--config`）已失效，未同步 `--scenario` |
| `migrate.sh` | 提示里的 `--skip rtmp` 已失效（`--skip` 移除），应改 `--scenario` |
