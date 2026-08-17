# rtmp 模块移除 ftp_server 前置压制（帮倒忙，加剧 FTP 线程堆积）

**日期**: 2026-08-17
**改动范围**: `modules/rtmp.py`（删除 run() 里 ensure_ftp(force=True) 前置调用）

---

## 一、问题描述

rtmp 模块 `run()` 开头会主动发一次 `ftp_server`（`ensure_ftp(force=True)`），本意是"压制 photo/video 之后固件 FTP 崩溃循环刷屏，给 rtmp 干净串口环境"。但结合真机排查，这个前置调用**帮倒忙**。

## 二、根因分析

1. **rtmp 已用 exec_async，不依赖哨兵**：推流命令 `rtmp_video_start` 用 `exec_async`，成败判据是 PC 端 ffprobe 探测，FTP 刷屏不影响判据。故"干净串口环境"这个前提已不存在。

2. **主动重发 ftp_server 加剧固件 FTP 崩溃循环**：真机 `ps` 查到板子堆积 15+ 个 `ftp` 线程（全 suspend 状态），是固件 FTP 崩溃循环的副产物——每次重启 FTP 服务都新建线程、旧线程 suspend 不回收。脚本再主动发 `ftp_server` 重拉一次，等于又触发一次重启，线程堆更多，CPU 被吃得更满，编码与推流更慢。

3. **与目标南辕北辙**：本意是"压制刷屏"，实际让本就过载的板子更过载。

## 三、修复内容

删除 `modules/rtmp.py` `run()` 中第 2 步的 `ensure_ftp(force=True)` 调用 + `time.sleep(1.0)`，替换为说明性注释（rtmp 不依赖 FTP，发 ftp_server 会加剧崩溃循环）。

## 四、验证结果

- `ast.parse` 语法 OK。
- **待真机验证**：跑 `python3 -m ATS.main --no-interactive-wifi --modules wifi_join,rtmp`，确认 rtmp 不再多发 ftp_server，且推流/探测正常。

## 五、还会再有吗（残留风险）

1. **固件 FTP 崩溃循环本身未解决**：本次只是停止"主动触发"，photo/video 模块仍会因下载文件触发固件 FTP 崩溃，其线程堆积问题依旧（属固件 bug，脚本不可根治）。后续应排查 photo/video 的 FTP 使用方式能否避免触发崩溃。
2. **若未来 rtmp 改用 exec_sync**：届时"干净串口环境"需求会回来，但也不该靠发 ftp_server 压制，而应靠分片写入/重试等其他手段。

## 六、经验沉淀

1. **"压制刷屏"要先问刷屏的成因**：本以为是"FTP 服务没起来"，实际上它正是"FTP 服务反复崩溃重启"的表现。发 ftp_server 重启服务，等于往崩溃循环里再喂一次。治标动作若不先查根因，可能反向加重。
2. **服务端崩溃循环的典型特征**：`service go wrong, now wait restarting` + 同名线程堆积（ps 看到多个 suspend 同名线程）= 固件 watchdog 无限重启且线程不回收。此时任何"再启动一次"的动作都是火上浇油。
3. **判据不依赖串口定界时，串口刷屏无需处理**：exec_async 的判据在 PC 端（ffprobe），串口刷屏只是噪声，不影响结果。这种情况下"清理串口环境"是伪需求。见 [[20260817_0203_RTMP探测失败_板子编码慢关键帧稀疏加大超时]]。
