# 新增需求：utest 细粒度判据（per-case 业务字符串检查）

> 状态：**草案待审核**（Document Agent 初稿，基于 `res/utestlog.txt` 分析，未动任何 ATS 代码）。
> 关联：ADR-012（utest 统一日志框架）、ADR-011（协议与判据分离）、ADR-013（串口探测指纹）。
> 目标读者：Code Agent（审核通过后照此实现）。

## 1. 背景与动机

当前 utest 判据只有一条：**testcase 级 result 行** `[  PASSED  ] [ result ] testcase (<name>)`（ADR-012 Decision 2）。
它的优点是固件已汇总、覆盖异构输出；缺点是「只看最后 PASSED，不看中间关键业务字符串」。

需求：对每个 utest case 做**更细的字符串检查**，不再简单判断最后的 PASSED。即除了 result 行，还要检查各 case 特有的业务输出关键字符串。

## 2. 现状

- 单文件模块：`ATS/modules/utest.py`（`@register("utest")`，一次动作 = 跑一个 testcase）
- 单文件协议：`ATS/drivers/utest_commands.py`（命令 / result 行正则 / 超时映射）
- 当前 scenario（`config/scenarios/utest.yaml`）有 **8 个 task**：efuse_test / filesystem / i2c_test / imu_test / pvt_auto_test / pvt_test / flash_xip_speed / flash_read
- `qspi_test` 已从 scenario 移除（next_step P1 第 3 条），但 `res/utestlog.txt` 仍有样本，`utest_commands.py` 的映射仍保留

## 3. 关键决策点（待人工拍板，阻塞实现）

| # | 决策点 | 选项 | 说明 |
|---|--------|------|------|
| D1 | 细查与 result 行的关系 | **叠加（推荐）** / 替代 | 叠加 = result 行仍是 PASS 必要条件，业务字符串为**补充校验**，二者都过才 PASS；替代 = 放弃 result 行，各 case 自扫业务字符串（推翻 ADR-012 Decision 2，需论证固件汇总不可靠） |
| D2 | 模块注册粒度 | **单模块 `utest` + 内部分派（推荐）** / 每 case 一模块 | 单模块保持 scenario 的 `- module: utest` + `override.testcase` 不变，改动最小；每 case 一模块则 scenario tasks 需改为 8 个不同 module 名 |
| D3 | 目录结构 | 见 §5 | modules 目录 `utest`（单数），drivers 目录 `utests`（复数，按用户命名） |
| D4 | 业务字符串缺失 / 中间态 | 见 §4 逐项 | `flash_read` 无业务输出、`qspi_test` 有合法 `1 lane fail!` |

> **Document Agent 推荐 D1=叠加、D2=单模块内部分派**：叠加兼容 ADR-012 既有设计、无需推翻 ADR；单模块内部分派符合模块红线（一次动作 + 参数接口），且 scenario 零改动。D4 逐项说明见下。

## 4. per-case 关键字符串分析（来自 `res/utestlog.txt`）

> 分析基础：固件统一日志已剥离 ANSI 色码后的纯文本。`[I/utest]` 前缀与三档分隔符为框架固定串，非业务判据。
> 「建议判据」为脚本侧应检查的**业务关键字符串**；正则待 Code Agent 沉淀到 `drivers/utests/<case>_commands.py`（ADR-011）。

### 4.1 efuse_test（2 个 unit）

业务输出：

```
EFUSE uart_baud[63:32] = 0x000f4240 (expect 0x000f4240)
EFUSE flash_vendor[15:14] = 0x1 (expect 0x1)
```

- **关键字符串**：两条 `EFUSE ... = <val> (expect <val>)` 行，且 `<val> == expect`。
- **建议判据**：出现 `EFUSE uart_baud[63:32] = 0x…(expect 0x…)` 且 `EFUSE flash_vendor[15:14] = 0x…(expect 0x…)`；严格模式下校验「= 值 == expect 值」（同组回引正则）。

### 4.2 filesystem（1 个 unit）

业务输出（关键三行）：

```
[I/utest] emmc card mount to /emmc is success
[I/utest] Elm filesystem write test data is success!
[I/utest] Elm filesystem read test data is success!
```

> 注：`[I/DFS.fs] the path:/emmc is not a mountpoint!` 是 mount 前的合法中间态，**不判失败**。

- **关键字符串**：mount 成功 + write 成功 + read 成功。
- **建议判据**：`emmc card mount to /emmc is success`、`write test data is success`、`read test data is success`。

### 4.3 i2c_test（5 个 unit）

业务输出（5 行，每 unit 一行，尾部均 `PASS`）：

```
i2c cpu wr: want 0x15 readback 0x15 PASS
i2c irq wr: want 0x15 readback 0x15 PASS
i2c dma wr: want 0x15 readback 0x15 PASS
i2c dma transmit: want 0x15 readback 0x15 PASS
i2c dma receive: expect 0x14 got 0x14 PASS
```

- **关键字符串**：5 个 sub-mode 各一行，尾部 `PASS`，覆盖 cpu / irq / dma / dma transmit / dma receive。
- **建议判据**：分别命中含 `cpu wr` / `irq wr` / `dma wr` / `dma transmit` / `dma receive` 且尾 `PASS` 的 5 行。

### 4.4 imu_test（1 个 unit）

业务输出：50 行 `imu[N]: irq=M G(...)mDPS A(...)ug T=...`，末尾汇总行：

```
IMU: collected 50/50 frames, irq 73->122
```

- **关键字符串**：`IMU: collected 50/50 frames`（帧数 50 完整采集）。
- **建议判据**：`IMU: collected 50/50 frames`（严格可校验 `50/50`，帧范围 `irq 73->122` 为辅）。

### 4.5 pvt_auto_test（2 个 unit）

业务输出：

```
PVT0 auto monitor started (irq=69)   # 出现 2 次（两个 unit 各 1 次）
PVT1 auto monitor started (irq=70)
```

- **关键字符串**：`PVT0 auto monitor started` 与 `PVT1 auto monitor started`（双通道都起）。
- **建议判据**：至少命中 `PVT0 auto monitor started` 且 `PVT1 auto monitor started`。

### 4.6 pvt_test（3 个 unit）

业务输出：

```
PVT single voltage: 0.783V
PVT single temperature: 35.115C
PVT convenience: vol=0.778V, temp=34.878C
```

- **关键字符串**：电压、温度、convenience 三行。
- **建议判据**：`PVT single voltage:`、`PVT single temperature:`、`PVT convenience:` 均出现。

### 4.7 flash_xip_speed（1 个 unit）

业务输出：

```
flash xip read speed: 6826 KB/s (size=1024 KB, time=150 ms)
```

- **关键字符串**：`flash xip read speed: <N> KB/s`。
- **建议判据**：命中 `flash xip read speed: \d+ KB/s`（速率数值是否设阈值需人工定，暂只判「有速率打印」）。

### 4.8 flash_read（1 个 unit）

业务输出：**无**（`jx_flash_test_read_unit` 无任何业务打印，仅有 result 行）。

- **关键字符串**：无业务字符串可查。
- **建议判据**：**退回 result 行判据**（细粒度无对象），或仅校验 unit 名 `jx_flash_test_read_unit` 出现。
- **待确认**：此 case 是否纳入「细粒度」范围，还是维持现状仅 result 行。

### 4.9 qspi_test（1 个 unit，当前 scenario 已移除，预留）

业务输出：

```
1 lane fail!     # 合法中间态，不判失败
1 lane pass!
2 lane pass!
4 lane pass!
...（多组 1/2/4 lane pass!）
```

- **关键字符串**：`2 lane pass!` 与 `4 lane pass!` 出现（证明高 lane 通过）。
- **建议判据**：命中 `2 lane pass!` 与 `4 lane pass!`；**严禁**把 `1 lane fail!` 判失败（ADR-012 已明确其为合法中间态）。
- **待确认**：是否本期恢复 qspi_test 进 scenario（当前已移除）。

## 5. 目录结构草案

> 仅结构草案，供 Code Agent 实施参考；D2（注册粒度）定后再定每个文件放什么。

```
ATS/modules/utest/            # 取代现有 ATS/modules/utest.py（需迁移，注意同名文件→目录冲突）
├── __init__.py               # 注册逻辑（单模块 utest 或 per-case 模块，视 D2）
├── base.py                   # 可选：utest 专用基类（提取 result 行公共判据）
├── efuse.py                  # per-case 封装（若 D2=每 case 一模块）
├── filesystem.py
├── i2c.py
├── imu.py
├── pvt_auto.py
├── pvt.py
├── flash_xip_speed.py
└── flash_read.py

ATS/drivers/utests/           # 取代现有 ATS/drivers/utest_commands.py（注意 utest_commands.py → utests/ 目录）
├── __init__.py
├── _common.py                # 公共：UTEST_RUN_COMMAND、UTEST_RESULT_RE、UTEST_TESTCASES 超时表
├── efuse_commands.py         # per-case 命令 + 业务关键字符串正则（ADR-011 唯一来源）
├── filesystem_commands.py
├── i2c_commands.py
├── imu_commands.py
├── pvt_auto_commands.py
├── pvt_commands.py
├── flash_xip_speed_commands.py
├── flash_read_commands.py
└── qspi_commands.py          # 预留（含 1 lane fail! 合法中间态说明）
```

## 6. 红线（实现必须遵守，与既有约定一致）

1. **ADR-011**：per-case 命令 / 判据 / 正则 / 超时唯一来源在 `drivers/utests/<case>_commands.py`，业务代码只 import，不内联协议字符串。
2. **模块红线**：每个 case 模块 = 一次测试动作 + 参数接口，不写 for、不感知场景；跑哪些 case 由 scenario 逐项声明。
3. **哨兵 ≠ 业务完成**：`exec_sync` 的 expect 必须是真实业务字符串（result 行或业务关键串），不能是命令回显。
4. **不扫 fail/error 关键字**：`qspi_test` 的 `1 lane fail!`、`filesystem` 的 `not a mountpoint!` 均为合法中间态，必须显式传白名单 expect，避开 serial_console 默认 `_ERROR_RE`。

## 7. 待人工确认清单

- [ ] D1：细查与 result 行是**叠加**还是**替代**？（推荐叠加）
- [ ] D2：模块注册粒度是**单模块内部分派**还是**每 case 一模块**？（推荐单模块）
- [ ] D3：目录命名确认（modules=`utest` 单数，drivers=`utests` 复数）？
- [ ] 4.7 flash_xip_speed 速率是否设**阈值**（如 < 某 KB/s 判失败），还是只判「有速率打印」？
- [ ] 4.8 flash_read 无业务输出，是否纳入细粒度（推荐退回 result 行，仅校验 unit 名）？
- [ ] 4.9 qspi_test 是否本期恢复进 scenario？
- [ ] per-case 正则的确切格式（本稿给的是「关键字符串」，最终正则由 Code Agent 落地，但需人工确认判据语义）
