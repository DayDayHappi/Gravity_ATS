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

## 文档过时点（后续顺手修）

| 位置 | 现象 |
|------|------|
| `config/system.yaml` | WiFi 默认值已再次变更为 `sw_test_24g`/`12345678`（commit `a9bf449`，历史候选 SW-test-2.4G/ftp_hw_2_4g/G-Demo/ftp_test_2_4G 已注释）；但 `ATS/README.md`、`archive/使用手册`、`archive/00_阅读导航` 仍写 `G-Demo`/`Gdemo@123` |
| `devlog 20260817_0203` L24/L37 | 写「1080p = 1296×2304」「板子分辨率只支持 4k/1080p 两档」——**错误**。ffprobe 实测（2026-09-08）：`cam_set video 1080p` → 1920×1080（横屏）；不发 cam_set 直接录 → 1296×2304（竖屏，固件默认）；`cam_set video 3k` → 2268×3024（竖屏）。1296×2304 是不发 cam_set 时的固件默认，非 1080p 档。正确映射见 current_status.md「固件行为快照」 |
| `modules/__init__.py` | 注释说 wifi 注册 scan/join，实际还注册了 `wifi_check` |
| `ATS/README.md` | 第 5 节哨兵机制仍写 `cmd; echo <TOKEN>`（旧写法），实际已改换行分隔 |
| 使用手册 | CLI 命令（`--modules`/`--skip`/`--config`）已失效，未同步 `--scenario` |
| `migrate.sh` | 提示里的 `--skip rtmp` 已失效（`--skip` 移除），应改 `--scenario` |
