# 测试用例（Test Case）

> 8 模块的判据汇总。当前结果：此前真机全部 PASS；Scenario 层重构后**待重新验证**。
>
> **normal 流程（ADR-008）**：WiFi/FTP 属 prepare 准备，不作为独立 task。normal tasks = emmc / photo / video / rtmp（4 项）。wifi_check 是 prepare.wifi_connect 收敛器内部的「状态检测器」，wifi_scan/wifi_join 退出默认流程（模块代码保留）。

## normal 独立测试项

| 用例 ID | 模块 | 输入 | 预期（成功判据） | 结果 |
|---------|------|------|------------------|------|
| TC-004 | emmc | `cd /emmc` | 无 error | PASS（重构前） |
| TC-006 | photo | `cam_set photo <mode>` + capture | 串口 `Capture completed successfully.` | PASS |
| TC-007 | video | `cam_set video` + start/stop | 串口 `Save Video Successful: <path>` | PASS |
| TC-008 | rtmp | `rtmp_video_start <url>` | ffprobe 探到 h264+分辨率 且 heartbeat 无超时 | PASS |

## prepare 环境准备项（不作 task，无独立报告项）

| 项 | 动作 | 判据 |
|----|------|------|
| wifi_connect | 收敛器：先 wifi_check 检测，未连才 join | `ctx.evb_ip` 就绪 |
| wifi_check | 状态检测器：ifconfig 有无非 0.0.0.0 IP | 有 IP → `wifi_ready=True` |
| ftp_ready | 幂等启 ftp_server + 建连接 | 列 `/emmc` 成功 |

## 保留模块（退出 normal 默认流程）

| 模块 | 说明 |
|------|------|
| wifi_scan | 手动调试 / 未来场景复用，RSSI < -70 只警告 |
| wifi_join | 手动调试 / 未来场景复用，`Got IP address : <IP>` |
| ftp | 代码保留，FTP 连通性由 prepare.ftp_ready 保证 |

## 判据要点

- photo：FTP 下载 JPEG 头（FFD8FF）+ 大小 > 10KB 为辅助，失败降级不判 FAIL；遍历 photo_modes。
- video：FTP 下载校验大小 > 100KB 为辅助。
- rtmp：不依赖 ftp；ffprobe 探测必须在 `rtmp_video_stop` 之前。

> 原始需求与判据定义见 `../03_development/archive/VX100_EVB_自动化测试_软件需求文档.md`。
