# 已知问题（Known Issues）

## 固件 bug（脚本无法根治，勿当脚本 bug 改）

| Issue | Impact | Workaround | Status |
|-------|--------|-----------|--------|
| ImuThread 崩溃 → ffplay 画面卡住 | 连续录 180s 视频 + 立即推流 ~3min 后 | 已整理 `RV_Backtrace` 线索转固件工程师；脚本靠 heartbeat 提前判 FAIL | 待固件修复 |
| FTP 崩溃循环 `service go wrong` 刷屏 | 拍照/录像后 | 只发一次 ftp_server + ensure_ftp 每次下载前重建连接 | 沿用 workaround |
| RTMP 命令卡死板子（串口零响应） | 未联网/状态异常时发 `rtmp_video_start` | 确保 WiFi 已连 + 摄像头就绪再发；卡死需物理重启 | 待固件修复 |
| RTMP 发送线程启动调度延迟 | 前一重负载结束到 RTMP 冷却间隔太短 | 前几十帧积压、首 IDR 延时大，属固件线程调度问题 | 待固件修复 |
| 关键帧(IDR)稀疏 | 1080p 编码慢 + FTP 刷屏抢 CPU | 探测超时放宽（-rw_timeout 15s），别用 640×480 经验值套大分辨率 | 待固件优化 |

排查先 grep serial.log 的 `RV_Backtrace` / `ImuThread` / `discontinuous frame` / `interp not finish in sof`。

## 文档过时点（后续顺手修）

| 位置 | 现象 |
|------|------|
| `config/system.yaml` | WiFi 默认 `SW-test-2.4G`/`tuf@3600`；但 `ATS/README.md`、`archive/使用手册`、`archive/00_阅读导航` 仍写 `G-Demo`/`Gdemo@123` |
| `config/modules/rtmp.yaml` | `heartbeat_timeout: 60`；rtmp_monitor 注释写默认 30（实际生效 60，以配置为准） |
| `modules/__init__.py` | 注释说 wifi 注册 scan/join，实际还注册了 `wifi_check` |
| `ATS/README.md` | 第 5 节哨兵机制仍写 `cmd; echo <TOKEN>`（旧写法），实际已改换行分隔 |
| 使用手册 | CLI 命令（`--modules`/`--skip`/`--config`）已失效，未同步 `--scenario` |
| `migrate.sh` | 提示里的 `--skip rtmp` 已失效（`--skip` 移除），应改 `--scenario` |
