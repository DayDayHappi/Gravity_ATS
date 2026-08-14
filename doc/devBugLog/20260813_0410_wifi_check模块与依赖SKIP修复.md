# 改进记录：wifi_check 模块 + 依赖 SKIP 逻辑修复

**时间**: 2026-08-13 04:10
**修改类型**: 功能改进 + Bug 修复
**影响模块**: `modules/wifi.py`（新增 wifi_check）、`main.py`、`core/runner.py`、`config/test_config.yaml`
**需求来源**: 用户提出--板子不下电连续测试时，WiFi 仍连着，第二次 join 会失败，应在 wifi 模块前先 ifconfig 检测，有 IP 则跳过 wifi 测试

---

## 一、需求与问题描述

板子第一次上电运行测试通过后，**不重启板子**再次运行时，WiFi 仍处于连接状态。此时 `wifi_join` 重新执行 `wifi join` 可能失败（板子已连，再 join 行为异常）。

**用户需求**：每次执行 wifi 模块前，先发 `ifconfig`，若已有 IP，则跳过 wifi 测试模块。

## 二、修改内容

### 2.1 `modules/wifi.py`：新增 wifi_check 模块

新增 `WifiCheckModule`（注册名 `wifi_check`），排在 wifi_scan 之前：
- 发 `ifconfig`，正则 `ip address\s*:\s*(\d+\.\d+\.\d+\.\d+)` 提取 IP
- 任一接口 IP 非 `0.0.0.0` 即视为已联网
- 已联网：标记 `ctx.skip_wifi=True` + 存 `ctx.evb_ip`，wifi_scan/wifi_join 据此 SKIP
- 未联网：正常继续 scan/join

新增辅助函数 `check_wifi_connected(console)` 供复用。

wifi_scan、wifi_join 的 `depends` 调整：
- `wifi_scan.depends = ["wifi_check"]`（原为 `[]`）
- `wifi_join.depends = ["wifi_scan"]`（不变）
- 两者 `run()` 开头检查 `ctx.skip_wifi`，True 则 SKIP

### 2.2 `main.py`：预清理去掉 `wifi disc`

```diff
-        console.exec_sync("wifi disc", timeout=8.0)        # 断开 WiFi
```

**原因**：预清理的 `wifi disc` 会与"有 IP 跳过 wifi"逻辑冲突--disc 后 ifconfig 永远检测不到 IP。改为不主动断开，由 wifi_check 检测决定跳过还是重连。

### 2.3 `config/test_config.yaml`：enabled_modules 加 wifi_check

```diff
 test:
   enabled_modules:
+    - wifi_check          # 先 ifconfig 检测，已联网则跳过 scan/join
     - wifi_scan
     - wifi_join
```

### 2.4 `core/runner.py`：模块配置映射 + 依赖 SKIP 逻辑修复

**配置映射**：`wifi_check` 映射到 `wifi` 配置段。

**依赖 SKIP 逻辑修复**（关键 bug）：

原逻辑有两个问题导致 wifi_scan SKIP 后，wifi_join 及后续模块被错误跳过：

1. **fail-fast 判定**（第 61 行）：依赖模块状态为 `SKIPPED` 也算"blocked"，导致 wifi_join 被跳过
   ```diff
   - blocked = [d for d in deps if self.module_status.get(d) in (FAILED, ERROR, SKIPPED)]
   + blocked = [d for d in deps if self.module_status.get(d) in (FAILED, ERROR)]
   ```
   **理由**：SKIP 是主动跳过（如已联网跳过 scan），不应阻断依赖模块；依赖模块自身的 run() 会再次检查条件决定是否 SKIP。

2. **`_overall_pass` 和 `module_status`**：SKIP 结果被记成 FAILED 状态
   ```diff
   - return result.status == PASSED
   + return result.status in (PASSED, SKIPPED)
   ```
   `module_status` 改为记录结果的真实状态（PASS/SKIP/FAIL），而非统一映射成 PASSED/FAILED。

## 三、验证结果

### 场景1：板子未连 WiFi（首次上电）

```
[PASS] wifi_check (68ms)  - 未联网，将继续 scan/join
[PASS] wifi_scan (2716ms) - 扫描到 7 个 AP
[PASS] wifi_join          - 已连接 G-Demo，IP=10.1.90.71
```
正常 scan + join。

### 场景2：板子已连 WiFi（不重启，第二次运行）

```
[PASS] wifi_check (44ms)  - 已联网，IP=10.1.90.71（跳过 wifi scan/join）
[SKIP] wifi_scan          - WiFi 已连接（IP=10.1.90.71），跳过扫描测试
[SKIP] wifi_join          - WiFi 已连接 (未知SSID/10.1.90.71)，跳过 join 测试
[PASS] emmc / ftp / photo / video   - 后续模块全部正常执行
测试完成：共 7 项 | 通过 5 | 失败 0 | 跳过 2 | 通过率 71.4%
```
检测到 IP -> 跳过 scan/join -> 后续 ftp/photo/video 不受影响，正常执行。

## 四、还会再有吗

**不会**。
- wifi_check 的 ifconfig 检测可靠（已验证两种场景）
- 依赖 SKIP 逻辑修复后，主动跳过不会误伤后续模块
- 连续运行无需重启板子，无需 wifi disc

## 五、经验沉淀

1. **SKIP 不等于 FAIL**：测试框架里"主动跳过"和"失败"语义不同，依赖链判定时 SKIP 不应阻断后续模块。这是测试框架的常见设计点。
2. **状态检测优于盲目重连**：用 ifconfig 先检测状态，避免在已连接状态下重复 join 导致失败。比预清理里 disc 再连更优雅。
3. **ifconfig vs wifi status**：ifconfig 看 IP（联网状态），wifi status 看 SSID/信号。本次只需判断"是否联网"，ifconfig 足够且更通用。
