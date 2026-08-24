# 测试用例（Test Case）

> 8 模块的判据汇总。当前结果：此前真机全部 PASS；Scenario 层重构后**待重新验证**。

| 用例 ID | 模块 | 输入 | 预期（成功判据） | 结果 |
|---------|------|------|------------------|------|
| TC-001 | wifi_check | `ifconfig` | 有非 0.0.0.0 IP | PASS（重构前） |
| TC-002 | wifi_scan | `wifi scan` | 表头 `SSID MAC security rssi chn Mbps` + ≥1 行 | PASS |
| TC-003 | wifi_join | `wifi join <ssid> <pwd>` | `Got IP address : <IP>`（异步约 9s） | PASS |
| TC-004 | emmc | `cd /emmc` | 无 error | PASS |
| TC-005 | ftp | `ftp_server` + 连接 | 列出 `/emmc` 成功 | PASS |
| TC-006 | photo | `cam_set photo <mode>` + capture | 串口 `Save Photo Successful: <dir>` | PASS |
| TC-007 | video | `cam_set video` + start/stop | 串口 `Save Video Successful: <path>` | PASS |
| TC-008 | rtmp | `rtmp_video_start <url>` | ffprobe 探到 h264+分辨率 且 heartbeat 无超时 | PASS |

## 判据要点

- wifi_scan：RSSI < -70 只警告不判失败。
- photo：FTP 下载 JPEG 头（FFD8FF）+ 大小 > 10KB 为辅助，失败降级不判 FAIL；遍历 photo_modes。
- video：FTP 下载校验大小 > 100KB 为辅助。
- rtmp：不依赖 ftp；ffprobe 探测必须在 `rtmp_video_stop` 之前。

> 原始需求与判据定义见 `../03_development/archive/VX100_EVB_自动化测试_软件需求文档.md`。
