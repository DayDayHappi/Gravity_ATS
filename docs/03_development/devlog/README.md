# devBugLog - 修改记录索引

本目录记录 ATS 脚本的所有修改（bug 修复、功能改进、重构等）。

## 规则

**每次对 ATS 代码的修改，都必须在本目录新建一个记录文档**，文件名格式：

```
<YYYYMMDD>_<HHMM>_<简短描述>.md
```

例如：`20260812_2302_修复连续运行emmc报错.md`

## 文档模板

每篇记录包含：

1. **问题描述**：现象、复现步骤、严重程度
2. **根因分析**：为什么会这样
3. **修复内容**：改了哪些文件、具体改动（diff 形式）
4. **验证结果**：修复后如何验证、结果数据
5. **还会再有吗**：是否彻底解决、有无残留风险
6. **经验沉淀**：可复用的排查思路或设计原则

## 文件清单

按时间倒序：

| 日期 | 文件 | 说明 |
|------|------|------|
| 2026-08-20 | [20260820_2246_ftp_ready下沉ftp_server启动幂等只发一次.md](20260820_2246_ftp_ready下沉ftp_server启动幂等只发一次.md) | 新增 start_ftp 幂等函数，ftp_ready 下沉 ftp_server 启动（全局只发一次），client 每次重建；修 stress 无 ftp 模块导致 FTP 未启动 |
| 2026-08-20 | [20260820_2124_按场景隔离日志与报告目录.md](20260820_2124_按场景隔离日志与报告目录.md) | 非 normal 场景日志/报告按场景隔离：logs/<场景>/logs/ + logs/<场景>/report/ |
| 2026-08-20 | [20260820_0833_引入测试场景层Scenario配置彻底拆分.md](20260820_0833_引入测试场景层Scenario配置彻底拆分.md) | 引入 Scenario 层：配置拆 system/modules/scenarios，Runner 支持 Task/repeat/loop，模块 run(params) 参数入口，--scenario 主入口 |
| 2026-08-20 | [20260820_0759_新增gitignore只跟踪ATS与tools.md](20260820_0759_新增gitignore只跟踪ATS与tools.md) | 新增 .gitignore 并 git rm --cached 取消跟踪 logs/reports/doc/handoff/res/.claude/pyc，仓库只保留 ATS 源码 + tools 内置 ffmpeg 二进制 |
| 2026-08-20 | [20260820_0414_RTMP推流持续性检测heartbeat机制与独立monitor模块.md](20260820_0414_RTMP推流持续性检测heartbeat机制与独立monitor模块.md) | 新增独立 RTMPMonitor 模块：用板端 [RTMP] f_index 作 heartbeat 持续检测推流稳定性，串口层只加原始数据 listener 不加业务逻辑；推流中途停止 5s 内判 FAIL，杜绝盲等 sleep 误判 PASS |
| 2026-08-20 | [20260820_0206_串口同步异步命令执行机制改造_exec_async去哨兵.md](20260820_0206_串口同步异步命令执行机制改造_exec_async去哨兵.md) | 抽离统一 _write_safe；exec_async 不再发送哨兵只发命令等业务 expect；rtmp expect 从命令回显改为 publish ready/Push Start、Push Stop/Stop requested；哨兵与业务完成语义分离 |
| 2026-08-20 | [20260820_0132_修复TX时间戳晚于RX的日志假象.md](20260820_0132_修复TX时间戳晚于RX的日志假象.md) | _write_cmd 的 TX 日志从分片循环后移到循环前：分片 sleep 会让 TX 时间戳后移到"发送完成"，晚于板子回显 RX 造成"先收后发"假象 |
| 2026-08-19 | [20260819_0436_测试结束询问问题记录到logs_problem目录.md](20260819_0436_测试结束询问问题记录到logs_problem目录.md) | 测试结束询问用户本次问题，有输入则记录到 logs/problem/<时间戳>.log（回车=无问题不记录），EOFError 兜底防无人值守卡死 |
| 2026-08-19 | [20260819_0231_录像模块拍摄与下载阶段日志及耗时.md](20260819_0231_录像模块拍摄与下载阶段日志及耗时.md) | video 模块加拍摄开始/结束、FTP 开始下载/下载完成日志及各自耗时，避免录像静默期和 FTP 大文件传输让人误判卡住 |
| 2026-08-18 | [20260818_2202_ffplay低延迟参数与模块计时进度日志.md](20260818_2202_ffplay低延迟参数与模块计时进度日志.md) | ffplay 参数换成低延迟直播(-rtmp_live live -rtmp_buffer 0 -fflags nobuffer -flags low_delay -framedrop -sync ext)，URL 复用运行时 pc_ip 不写死；runner 用 time.monotonic+try/finally 给各模块开始/结束计时打印；rtmp 600s 推流改每 30s 打进度防误判卡住 |
| 2026-08-18 | [20260818_0319_rtmp推流与ffplay改为10分钟可手动关闭.md](20260818_0319_rtmp推流与ffplay改为10分钟可手动关闭.md) | rtmp 推流时长与 ffplay 展示都改 10 分钟(stream_duration=600)；原 stream_duration 是死配置、真正时长藏在 ffplay_show_duration，统一到 stream_duration 控制推流持续，删除冗余 ffplay_show_duration；ffplay 独立窗口跟随流播放、用户可手动关 |
| 2026-08-17 | [20260817_2311_ftp冷启动必须等service_launched再connect.md](20260817_2311_ftp冷启动必须等service_launched再connect.md) | 删预清理后 ftp 冷启动：init success 到 service launched 有约 3.4s 延迟，脚本只等 init success 就 connect 撞上未 listen 窗口 Connection refused；改 exec_async 等 service launched 再连 |
| 2026-08-17 | [20260817_2241_ftp每次下载前重建连接_应对3s空闲超时.md](20260817_2241_ftp每次下载前重建连接_应对3s空闲超时.md) | 板子 FTP 服务端 3s 空闲即断会话，旧代码缓存复用连接导致拍照/录像后下载失败；改为每次下载前重建独立连接(connect 恢复工作目录+关旧 socket)，ensure_ftp 不再探测旧连接，数据连接由 ftplib 主动模式每次换新端口 |
| 2026-08-17 | [20260817_0628_ftp_server只启动一次去除重复重启噪音.md](20260817_0628_ftp_server只启动一次去除重复重启噪音.md) | main.py 预清理 + ensure_ftp(force=True) 都会重发 ftp_server，叠加起来多次触发固件崩溃循环刷屏；改为全程只在 ftp 模块启动一次，ensure_ftp 只重连 PC 端客户端；wifi join 成功后加 sleep(5) 等状态稳定 |
| 2026-08-17 | [20260817_0309_rtmp移除ftp_server前置压制.md](20260817_0309_rtmp移除ftp_server前置压制.md) | rtmp 模块删除 run() 里 ensure_ftp(force=True) 前置调用：rtmp 不依赖 FTP 且重发 ftp_server 会加剧固件 FTP 崩溃循环/线程堆积拖慢推流 |
| 2026-08-17 | [20260817_0248_ffplay画面确认改用独立终端窗口播放.md](20260817_0248_ffplay画面确认改用独立终端窗口播放.md) | ffplay 画面确认改用 gnome-terminal 独立终端窗口播放(去 -rw_timeout 耐心等关键帧)；窗口生命周期独立于脚本，teardown 不再 kill |
| 2026-08-17 | [20260817_0203_RTMP探测失败_板子编码慢关键帧稀疏加大超时.md](20260817_0203_RTMP探测失败_板子编码慢关键帧稀疏加大超时.md) | rtmp 探测失败根因是板子推1080p编码慢+FTP刷屏抢CPU→关键帧IDR稀疏(600帧/57s一个)；ffprobe -rw_timeout 3s→15s、analyzeduration/probesize放宽、重试加大，耐心等IDR |
| 2026-08-17 | [20260817_0141_ffplay画面确认增强_stderr落日志与展示延长.md](20260817_0141_ffplay画面确认增强_stderr落日志与展示延长.md) | ffplay 画面确认 stderr 从 DEVNULL 改落 logs/<ts>/ffplay.log；探测到流后、stop 前延长展示窗口(新增 ffplay_show_duration 配置)，解决"启动了但看不到窗口" |
| 2026-08-17 | [20260817_0115_RTMP命令串口溢出丢字节_长命令分片写入修复.md](20260817_0115_RTMP命令串口溢出丢字节_长命令分片写入修复.md) | rtmp 推流命令(45B+哨兵77B)超板子串口缓冲RT_SERIAL_RB_BUFSZ(64B)溢出丢字节，命令截断报command not found；serial_console 新增 _write_cmd 分片+片间延时写入 |
| 2026-08-14 | [20260814_0500_MediaMTX换nginx-rtmp.md](20260814_0500_MediaMTX换nginx-rtmp.md) | 删除内置 MediaMTX，RTMP 服务端改用系统 nginx-rtmp（仅检查就绪不启停）；验证改 ffprobe 实时探测+可选ffplay，去存盘；cam1→cam 统一 |
| 2026-08-14 | [20260814_0010_新增migrate迁移脚本.md](20260814_0010_新增migrate迁移脚本.md) | 新增 `migrate.sh` 一键迁移脚本(8项检查+收集sudo命令)+`迁移指南.md`，用于换 Ubuntu PC 时初始化环境 |
| 2026-08-13 | [20260813_0535_新增串口终端模式.md](20260813_0535_新增串口终端模式.md) | 新增 `--terminal` 交互式串口终端(类Xcom)：手动发命令、实时看TX/RX、Tab切ANSI，用于RTMP等调试 |
| 2026-08-13 | [20260813_0500_RTMP服务端与拉流时序修复.md](20260813_0500_RTMP服务端与拉流时序修复.md) | RTMP 真机验证打通：引入 MediaMTX 服务端中转 + 修 ffmpeg 拉流参数(-reconnect 不兼容) + 先推后拉时序 + exec_async 抗 FTP 刷屏（4 层根因） |
| 2026-08-13 | [20260813_0400_内置ffmpeg打通RTMP依赖.md](20260813_0400_内置ffmpeg打通RTMP依赖.md) | 引入预编译静态 ffmpeg/ffprobe 到 tools/ffmpeg/，配置指向内置二进制，打通 RTMP 离线依赖（零代码改动） |
| 2026-08-13 | [20260813_0243_照片路径与视频断点续传下载.md](20260813_0243_照片路径与视频断点续传下载.md) | 照片下载打印路径；视频下载到本地（断点续传+socket超时，解决FTP卡死） |
| 2026-08-13 | [20260813_0410_wifi_check模块与依赖SKIP修复.md](20260813_0410_wifi_check模块与依赖SKIP修复.md) | 新增 wifi_check 模块（ifconfig 检测有IP跳过wifi）；修复依赖链 SKIP 误伤后续模块 |
| 2026-08-12 | [20260812_2302_修复连续运行emmc报错.md](20260812_2302_修复连续运行emmc报错.md) | emmc 连续运行报错（目录残留 + FTP 刷屏），cd 改绝对路径 + 预清理加 cd / |

## 另含

- `20260812_开发过程报告.md`：初版开发的完整过程报告（含 10 个问题的排查）
- `20260812_使用手册.md`：脚本使用手册
