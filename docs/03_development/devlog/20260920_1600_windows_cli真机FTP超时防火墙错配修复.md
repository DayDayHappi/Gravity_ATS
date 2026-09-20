# Windows CLI 真机 FTP 超时根因修复（防火墙规则错配）

## Date
2026-09-20

## Task
`feature/windows-cli` 真机 stress 测试中 photo 每项 ~68s，根因定位为 Windows 防火墙规则错配导致 FTP 主动模式数据端口回连被拦截。排查并修复，实测 LIST 恢复 0.21s。

## Changed
无源码改动（纯环境/防火墙规则修复 + devlog 留痕）。

## Files
无源码文件改动。

## Reason
- 日志证据（`logs/stress/20260920/20260920_154544/run.log` L26）：EVB WiFi 连接成功 IP = **192.168.1.100**；FTP list 每次 `timed out` 重试 3 次，photo 每项 ~69s。
- 诊断（ftplib 主动模式）：`ftp.sock.getsockname()` = `('192.168.1.103', 49262)`，PORT 命令通告本机 IP = **192.168.1.103**，EVB 回连 `192.168.1.103:高位端口`。
- 原防火墙规则 `Gravity ATS CLI FTP - Board101` 三处错配：
  1. `RemoteAddress = 192.168.1.101`（凭空地址，EVB 实为 .100）
  2. `LocalAddress = 192.168.1.100`（把 EVB 当本机了，本机实为 .103）
  3. `Program = 系统 Python313\python.exe`（实际用 `.venv-cli` 的 python，不匹配）
  → 规则与实际流量（.100 回连 .103）完全相反，放行从未生效。

## Verification
- 修复前：真实 EVB FTP `retrlines('LIST')` 反复 `timed out`。
- 修复后规则：`RemoteAddress=192.168.1.100`、`LocalAddress=Any`、`Program=Any`、`LocalPort=1024-65535`、`Profile=Public`。
- 实测：真实 EVB FTP `LIST` **0.21s** 返回 2 个目录（dev / emmc），主动模式回连链路通。

## Known limitation
- photo 每项时长是否回到 ~13s 待完整 stress 真机复验。
- 多网卡时 PORT 回连 IP 由 ftplib 按控制连接源 IP（.103）通告，单一测试网卡下已正确；若未来加网卡需留意路由（交接报告 TODO-CONFIRM）。
