# Windows CLI 真机 FTP 主动模式超时 排查与解决报告

**日期**: 2026-09-20
**性质**: 环境/防火墙配置问题（非脚本 bug，脚本源码零改动）
**影响**: `feature/windows-cli` 分支真机 stress 测试中 photo 每项 ~68s（正常应 ~13s）
**结论**: Windows 防火墙入站规则三处字段错配，FTP 主动模式数据端口回连被拦截，修复后 LIST 恢复 0.21s

---

## 一、现象

Windows 下运行 `python -m ATS.main --scenario stress --no-interactive-wifi`，photo 模块每一项都卡在
FTP 列目录，约 68s 才 PASS，整轮 stress（10 个 photo + 12 个 video + 1 rtmp）被拖得极慢。

日志铁证（`logs/stress/20260920/20260920_154544/run.log`）：

```
[15:46:37.612] [INFO] WiFi 连接成功: sw_test_24g / IP=192.168.1.100   ← EVB 实际 IP
[15:47:08.442] [DEBUG] FTP list 失败(尝试 1): timed out，重连...
[15:47:18.740] [DEBUG] FTP list 失败(尝试 2): timed out，重连...
[15:47:29.036] [DEBUG] FTP list 失败(尝试 3): timed out，重连...
[15:48:01.606] [PASS] photo[auto] (69587ms) - 拍照成功...
```

> 注意：photo 最终是 PASS（拍照动作本身成功），只是「列目录找新增 jpg 做辅助验证」这一步每次都
> 超时重试 3 次、每次约 10s，把单项耗时从 ~13s 拉长到 ~68s。

---

## 二、为什么先怀疑防火墙（而不是脚本）

本分支是刚做完 Windows 移植的新环境，第一反应容易怀疑「平台抽象层移植出 bug」。但关键线索是：

1. **EVB 侧正常**：拍照、WiFi、串口探测、ffplay 拉起全部正常，唯独 FTP 数据通道超时。
2. **控制连接正常、数据连接不通**：FTP 登录（`USER/PASS`，走 21 端口控制连接）每次都秒成，
   只有 `LIST`（需要另开一条**数据连接**）超时。这是典型的「主动模式回连被拦」特征。
3. **FT​P 模块注释早有预警**（`ftp_client.py` L35-36）：
   > 主动模式需 PC 防火墙放行入站数据端口（或临时关闭防火墙）。

所以方向锁定为 Windows 防火墙拦了 FTP 主动模式的入站数据端口。

---

## 三、FTP 主动模式原理（理解根因的前提）

RT-Thread 固件的 FTP 服务**只支持主动模式**（不支持 PASV，配置里 `pasv: false`）：

```
1. PC ── 控制连接(端口21) ──> EVB      PC 发 USER/PASS 登录（这条一直通）
2. PC 监听一个本地高位端口(如 49263)，通过控制连接发 PORT 命令告诉 EVB：
   "请连接我的 192.168.1.103:49263"
3. EVB ── 主动回连数据端口(49263) ──> PC   ← 这条被防火墙拦
4. 数据通道建立后，LIST/RETR 的数据从这里传
```

**关键点**：数据连接是 EVB **主动向 PC 回连**，对 PC 来说是一条**入站（Inbound）TCP 连接**。
Windows 防火墙默认拦截入站，必须有规则放行，否则 EVB 的回连 SYN 被静默丢弃，PC 一直等不到数据
→ LIST 超时。

---

## 四、诊断过程（可复现）

### 第 1 步：确认 EVB 与 PC 的实际 IP

```powershell
# PC 各网卡 IPv4（排除回环 127.* 和链路本地 169.254.*）
Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
  $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*'
}
```

输出（本机当时状态）：

```
vEthernet (Default Switch)  172.19.48.1       # Hyper-V 虚拟交换机，无关
WLAN                        10.1.64.183       # 无线（连 GravityXR.local，无关）
以太网                      192.168.1.103     # 连 sw_test_24g，测试网卡 ← PC 实际 IP
```

EVB 的 IP 从 `run.log` 第 26 行拿：`WiFi 连接成功: sw_test_24g / IP=192.168.1.100`。

> **PC = 192.168.1.103，EVB = 192.168.1.100**，这是后续一切判断的基准。

### 第 2 步：检查防火墙里已有的放行规则

```powershell
Get-NetFirewallRule -DisplayName "Gravity ATS CLI FTP - Board101" |
  Get-NetFirewallAddressFilter
```

输出（问题所在）：

```
LocalAddress  : 192.168.1.100     ← 错了！这是 EVB 的 IP，被当成「本机」了
RemoteAddress : 192.168.1.101     ← 错了！凭空地址，EVB 实际是 .100
```

再看程序绑定：

```powershell
Get-NetFirewallRule -DisplayName "Gravity ATS CLI FTP - Board101" |
  Get-NetFirewallApplicationFilter
```

输出：

```
Program : C:\Users\...\Python313\python.exe    ← 错了！实际用 .venv-cli 的 python
```

### 第 3 步：决定性诊断 —— ftplib 主动模式到底通告哪个 IP、哪个端口

直接连真实 EVB FTP，看 ftplib 的 PORT 命令填的是什么：

```python
import socket
from ftplib import FTP

ftp = FTP()
ftp.connect('192.168.1.100', 21, timeout=10)   # EVB 控制连接
ftp.login('loogg', 'loogg')
print('control local sockname:', ftp.sock.getsockname())
```

输出：

```
login: 230 User logged in
control local sockname: ('192.168.1.103', 49262)   # PC 实际 IP .103
```

**结论**：ftplib 会通告 `192.168.1.103`（PC 正确 IP）+ 一个高位端口，让 EVB 回连。
而防火墙规则写的是「放行 `.101` 访问 `.100`」，与实际流量（`.100` 回连 `.103`）完全相反 → 拦截。

---

## 五、根因

防火墙规则 `Gravity ATS CLI FTP - Board101` 有**三处字段错配**，导致放行从未真正生效：

| 字段 | 规则里的值（错） | 应该是 | 说明 |
|------|----------------|--------|------|
| **RemoteAddress** | `192.168.1.101` | `192.168.1.100` | 凭空地址；EVB 实际 IP 是 .100 |
| **LocalAddress** | `192.168.1.100` | `Any`（本机 .103） | 把 EVB 的 IP 填成了「本机」，方向反了 |
| **Program** | 系统 `Python313\python.exe` | `Any`（venv 也能用） | 实际用 `.venv-cli\Scripts\python.exe` 跑，程序不匹配 |
| LocalPort | `1024-65535` | `1024-65535` | ✅ 这个本来对 |
| Profile | `Public` | `Public` | ✅ 这个本来对（测试网卡 sw_test_24g 是 Public） |

三个错配叠加：即使端口范围和 profile 对，因为 IP 方向写反 + 程序绑定错，规则一条流量都没匹配上。

---

## 六、解决方案

### 修复命令（需管理员 PowerShell）

**右键「开始菜单 → Windows PowerShell(管理员)」**，执行：

```powershell
Remove-NetFirewallRule -DisplayName "Gravity ATS CLI FTP - Board101" -ErrorAction SilentlyContinue

New-NetFirewallRule -DisplayName "Gravity ATS CLI FTP - Board101" `
  -Direction Inbound -Action Allow -Protocol TCP `
  -LocalPort 1024-65535 `
  -RemoteAddress 192.168.1.100 `
  -Profile Public
```

修复后规则语义：**允许 EVB（192.168.1.100）回连本机任意 IP 的 1024-65535 高位端口**（FTP 主动模式数据通道）。

### 为什么这么配

- `RemoteAddress = 192.168.1.100`：只放行 EVB 这台设备的回连，最小暴露面。
- `LocalAddress` 不写（=Any）：避免本机 IP 变动（DHCP 换 IP）后规则又失效——这是上次踩坑的教训。
- `Program` 不写（=Any）：避免 venv / 系统 python 路径差异再坑一次。
- `LocalPort 1024-65535`：ftplib 主动模式每次 `makeport()` 起的是高位临时端口。

### 验证命令

```powershell
Get-NetFirewallRule -DisplayName "Gravity ATS CLI FTP - Board101" |
  Get-NetFirewallAddressFilter
```

正确输出应为：

```
LocalAddress  : Any
RemoteAddress : 192.168.1.100
```

---

## 七、修复后验证

直接对真实 EVB FTP 做一次 LIST（不跑完整测试，快速确认）：

```python
import time
from ftplib import FTP

t0 = time.time()
ftp = FTP()
ftp.connect('192.168.1.100', 21, timeout=10)
ftp.login('loogg', 'loogg')
ftp.set_pasv(False)              # 主动模式
lines = []
ftp.retrlines('LIST', lines.append)
print(f'LIST OK, {len(lines)} entries, 耗时 {time.time()-t0:.2f}s')
ftp.close()
```

修复后输出：

```
LIST OK, 2 entries, 耗时 0.21s
   dr-xr-xr-x 1 admin admin 0 Jan 01 1970 dev
   dr-xr-xr-x 0 admin admin 0 Dec 31 1979 emmc
```

**从超时（>10s×3 次重试）恢复到 0.21s**，问题解决。

---

## 八、排查时间线回顾

| 阶段 | 动作 | 结论 |
|------|------|------|
| 1 | 读 `run.log` 定位卡点 | photo 每项 ~68s，FTP list 反复 timed out |
| 2 | 确认 EVB/PC IP | EVB=.100，PC=.103 |
| 3 | 查防火墙规则 | RemoteAddress=.101、LocalAddress=.100、Program=系统 python，全错配 |
| 4 | ftplib 诊断 | PORT 通告 PC=.103，规则与实际流量方向相反 |
| 5 | 提权重配规则 | 需管理员权限（当前 shell 无管理员，先失败） |
| 6 | UAC 提权（脚本文件方式） | 规则改对：RemoteAddress=.100、LocalAddress=Any、Program=Any |
| 7 | 真实 FTP LIST | 0.21s 成功，链路通 |

---

## 九、复用价值（以后再遇到怎么快速定位）

1. **先看日志区分「控制连接」和「数据连接」**：
   - 登录秒成 + LIST/RETR 超时 = 主动模式数据端口被拦（防火墙）。
   - 登录都超时 = 网络不通 / EVB 未起 FTP / IP 错。
2. **确认三个 IP 基准**：EVB IP（看 `run.log` 的 WiFi 连接成功行）、PC 测试网卡 IP、防火墙规则的
   RemoteAddress 三者是否一致。
3. **确认程序绑定**：规则如果绑了 `Program`，必须与实际运行的 `python.exe` 路径一致（venv 和系统 python 是两个文件）。
4. **最小验证**：不用跑完整测试，直接用 `ftplib.retrlines('LIST')` 一条命令验证数据通道。

---

## 十、关联文档

- devlog：`20260920_1600_windows_cli真机FTP超时防火墙错配修复.md`
- 交接文档（Document Agent 维护）：`docs/05_handoff/windows_cli_status.md`（「真机已知问题」表，待回填为已解决）
- 相关源码：`ATS/drivers/ftp_client.py`（主动模式封装，本问题**未改**此文件）
