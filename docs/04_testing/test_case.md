# 测试用例（Test Case）

> 8 模块的判据汇总。当前结果：此前真机全部 PASS；Scenario 层重构后**待重新验证**。
>
> **normal 流程（ADR-008）**：WiFi/FTP 属 prepare 准备，不作为独立 task。normal tasks = emmc / photo / video / rtmp（4 项）。wifi_check 是 prepare.wifi_connect 收敛器内部的「状态检测器」，wifi_scan/wifi_join 退出默认流程（模块代码保留）。

## normal 独立测试项

| 用例 ID | 模块 | 输入 | 预期（成功判据） | 结果 |
|---------|------|------|------------------|------|
| TC-004 | emmc | `cd /emmc` | 无 error | PASS（重构前） |
| TC-006 | photo | `cam_set photo <mode>` + capture | 串口 `Capture completed successfully.` | PASS |
| TC-007 | video | `cam_set video` + start/stop | 串口 `Video recording completed successfully.` | PASS |
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

## 独立能力压测（power_switch，ADR-015）

> 上下电控制模块是 driver 能力（非测试模块，不进 scenario tasks）。其可靠性需独立压测验证。

### TC-PS-001 串口控制器交替上下电压测（2 周期 × 15min，仅控制器·不接 EVB 板）

| 项 | 值 |
|----|-----|
| 目标 | 验证串口上下电控制模块**本身**（不接 EVB 板）长时间低频上下电的可靠性：发帧成功、响应帧正确、长连接稳定 |
| 前置 | `system.yaml` 的 `power_switch.enabled: true`；**仅接串口控制器**（不接 EVB 板；控制器独立供电，空载也能切状态并回帧） |
| 节拍 | 上电保持 15min → 下电保持 15min 交替；周期 30min；共 2 周期 = 1h（2 次上电 + 2 次下电，共 4 次状态切换） |
| 测试对象 | 控制器本身（发帧/回帧/状态切换），**不涉及 EVB 板**，无需防接反 |
| 判据 | 每次发帧后收到合法 4 字节状态帧（`A0 01 <state> <sum>`，state∈{0x00,0x01} 且校验和正确）；上电后期望回 ON（`A0 01 01 A2`）为硬判据；下电后回帧不严格要求 OFF（见下）；全程不重开串口（长连接），结束后连接仍存活 |
| 结果 | **待真机**（旧 30 周期×10s 版本已 PASS，见下） |

> 历史：原版为「上电 10s / 下电 10s，30 周期，10min」，真机 2026-09-21 PASS。2026-09-21 起改为「15min / 15min，2 周期，1h」的低频长保持版本。

**下电判据（固件特性，ADR-015 实测）**：控制器响应帧返回的是**切换前状态**（下电前 ON → 回 `A0 01 01 A2`；已 OFF → 回 `A0 01 00 A1`），**发一次即生效**，无需轮询。故下电判据为「收到合法状态帧」而非「必回 OFF」；只有上电回 ON 作为硬判据。旧 30 周期×10s 真机压测全部回合法帧，下电每轮均生效（回 `01` = 切换前 ON，切到 OFF）。

**已实现（Code Agent，devlog `20260921_1330`/`20260921_1402`/`20260921_1436`）**：`power_on()/power_off()` 已增强为「发帧 + 读响应」返回，读空自动重试一次；`is_valid_state_frame`/`frame_state` 判据沉淀到 `power_commands.py`；控制器通信写独立 `power_switch.log`。压测入口 `python3 -m ATS.main --power-stress`。
