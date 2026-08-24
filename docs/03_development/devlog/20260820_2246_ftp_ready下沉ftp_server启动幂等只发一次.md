# ftp_ready 下沉 ftp_server 启动，幂等只发一次

**日期**: 2026-08-20
**改动范围**: `modules/ftp.py`（新增 `start_ftp`）、`core/scenario_manager.py`（`ftp_ready` 动作实化）

---

## 一、问题描述

压测场景 stress.yaml 的 tasks 只含 photo/video/rtmp（无 ftp 模块），而 `ftp_server` 命令
唯一发起点在 `ftp` 模块 run() 里，导致压测时板端 FTP 服务从未启动，串口日志看不到
ftp_server；photo/video 因 `ctx.ftp_client` 为 None 而被 SKIP。

## 二、根因分析

`ftp_ready` prepare 动作原本只是「检查 evb_ip 是否存在」的空壳（ftp_server 启动逻辑
留在 ftp 模块），名字却暗示"FTP 就绪"。stress 依赖 prepare 完成 FTP 启动，但实际没人发
ftp_server，语义与实现不一致。

## 三、修复内容

新增 `start_ftp(ctx, console, cfg)`，供 prepare 与 ftp 模块共用，保证：

1. **ftp_server 全程只发一次**：`ctx.ftp_server_started` 标志幂等，loop 多轮不重发，
   避免触发固件 "service go wrong, now wait restarting" 崩溃循环。
2. **client 每次重建**：板子 FTP 服务端 3s 空闲断开会话但一直 listen，脚本侧始终是
   无状态 client，`ensure_ftp` 每次下载前重建连接，不缓存复用。

`ftp_ready` 动作改为调用 `start_ftp` 真正启动 FTP；`ftp` 模块 run 也改调 `start_ftp`
（prepare 已启动则只重建连接，不重发 ftp_server）。

## 四、验证结果

- `python3 -m py_compile` 通过；三场景 `--dry-run` 通过。
- `start_ftp` 幂等单测：loop 3 轮只发 1 次 ftp_server；无 evb_ip 不发命令返回 None；
  启动失败返回 None 且不置 `ftp_server_started`（可下次重试）。

## 五、还会再有吗

- **待真机验证**：normal 场景 prepare 已启动 FTP 后，ftp 模块 run 不再重发 ftp_server
  且列目录验证通过；stress 场景 ftp_ready 启动 FTP 后 photo/video 正常复用。
- **stress 的 wifi 前置仍缺**：`--no-interactive-wifi` 下 `wifi_connect` 跳过且 stress 无
  wifi_join 模块，evb_ip 拿不到，ftp/photo/video/rtmp 全会失效（交互 wifi 或板子已连时不受影响）。
  需单独确认 stress 的 wifi 连接策略。

## 六、经验沉淀

- **幂等动作要落到「只发一次」的显式标志**：像 ftp_server 这种"重发触发固件 bug"的命令，
  用 ctx 标志 + 下沉到 prepare 动作，loop 语义才不会把它重复执行。
- **prepare 动作名要名副其实**：`ftp_ready` 若只做检查就别叫 ready；要么实化（真正启动），
  要么改名（如 `check_evb_ip`），避免误导。
