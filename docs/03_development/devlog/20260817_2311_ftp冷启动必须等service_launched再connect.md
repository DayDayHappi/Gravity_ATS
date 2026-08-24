# FTP 服务冷启动时序：必须等 service launched 再 connect，否则 Connection refused

**日期**: 2026-08-17
**改动范围**: `modules/ftp.py`（`FtpModule.run()` 改用 exec_async 等 ``service launched success``，删除 `_FTP_OK_RE` 常量）

---

## 一、问题描述

上一轮把 `main.py` 预清理阶段的 `ftp_server` 删除后（[[20260817_0628_ftp_server只启动一次去除重复重启噪音]]），完整跑一遍测试，**ftp 模块 FAIL**：

```
[22:57:11.035] [DEBUG] FTP 连接失败(尝试 1/3): [Errno 111] Connection refused
[22:57:12.088] [DEBUG] FTP 连接失败(尝试 2/3): [Errno 111] Connection refused
[22:57:13.130] [DEBUG] FTP 连接失败(尝试 3/3): [Errno 111] Connection refused
[22:57:14.131] [FAIL] ftp - FTP 客户端连接失败: FTP 连接失败（重试 3 次）: [Errno 111] Connection refused
```

photo/video 因依赖 ftp 被 SKIP。

## 二、根因分析

对比 serial.log 时间线：

```
22:57:09.153  TX> ftp_server
22:57:10.947  RX< [FTP] Ftp server init success!!!   ← exec_sync 哨兵返回，脚本立即 connect
22:57:11~13   PC 端 connect 重试 3 次（间隔 1s）→ 全部 Connection refused
22:57:14.331  RX< [I/ftp] service launched success.   ← 3.4s 后服务才真正 listen 21 端口
```

1. **"init success" ≠ "已 listen"**：`ftp_server` 冷启动分两阶段——先打印
   `Ftp server init success`（初始化完成），约 3.4s 后才打印
   `service launched success`（FTP 会话线程真正建立、开始监听 21 端口）。

2. **脚本等错标志**：旧代码 `exec_sync("ftp_server", expect=_FTP_OK_RE)` 的
   `_FTP_OK_RE = "Ftp server init success|service launched success"` 会匹配到
   先出现的 "init success"（哨兵也在此时返回），脚本随即 `connect()`，此时服务
   还没 listen，重试窗口（`connect_retry:3` × `connect_interval:1.0` ≈ 3s）覆盖
   不到 "launched" 时刻（+3.4s），故全部 `Connection refused`。

3. **为什么之前能过**：旧版 `main.py` 预清理在 wifi 连接**前**就发过一次
   `ftp_server`，等到 ftp 模块执行时已过去几十秒，服务早已 warm（listen 稳定），
   第二次 `ftp_server` 无论等哪个标志都不会撞上空窗期。删除预清理后变成冷启动，
   首次暴露这个时序缺陷。

## 三、修复内容

`FtpModule.run()` 改为用 `exec_async` 持续等真正的 listen 标志，事件驱动而非
固定 sleep：

```python
r = console.exec_async("ftp_server",
                       expect=r"service launched success",
                       result_timeout=15.0)
if not r.success:
    return self._fail("FTP 服务启动失败（未等到 service launched）", detail=r.clean)
```

- `exec_async` 不等哨兵，直接在整个 `result_timeout` 内持续读流匹配
  `service launched success`，出现即返回，保证后续 `connect()` 时服务已 listen。
- 删除已无用的 `_FTP_OK_RE` 常量（及随之失效的 `import re`）。

## 四、验证结果

- `ast.parse` 语法检查 `ftp.py` OK。
- **待真机验证**：完整跑一遍，确认 ftp 模块不再 Connection refused，photo/video
  正常执行（下载前重建连接的逻辑也在本次一并验证）。

## 五、还会再有吗（残留风险）

1. 若固件版本打印的 launched 标志文案不同（如 "service launched" 无 "success"），
   `exec_async` 会等满 15s 超时判失败。当前固件稳定打印 `service launched success.`，
   暂不担心；未来换固件需留意此文案。
2. `ftp_server` 全局仍只发这一次（确认唯一发送点），不引入重复重启噪音。

## 六、经验沉淀

1. **服务启动是分阶段的，别拿"初始化完成"当"就绪"**：`init success` 与
   `service launched` 之间可能隔着秒级的异步初始化（线程创建、端口 bind），
   判据必须选真正"对外可用"的那个标志，而不是最先打印的那个。
2. **删掉"预热"动作会暴露下游的时序假设**：删预清理的 `ftp_server` 是正确方向
   （消除重复重启），但它顺带承担了"提前几秒把服务拉起来"的隐性作用。删除后
   要把这个时序责任显式补回真正的启动点（FtpModule.run 等 launched），而不是
   靠前面模块的副作用。
3. 与 [[20260817_0628_ftp_server只启动一次去除重复重启噪音]] 配合：那边保证"只发
   一次"，这边保证"这一次要等它真正起来"，两者合起来才是完整的启动语义。
