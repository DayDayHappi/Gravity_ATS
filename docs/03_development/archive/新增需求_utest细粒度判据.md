# 新增需求：utest 细粒度判据（per-case 业务字符串检查）

> 状态：**已实施（Code Agent 2026-09-17，devlog `20260917_1824_utest细粒度判据实施.md`）**。
> 关联：ADR-012（utest 统一日志框架）、ADR-011（协议与判据分离）、ADR-013（串口探测指纹）。
> 目标读者：Code Agent（按本文档实施）。
> 决策记录：§3 为人工最终拍板，实施以 §3 为准，不再协商。

## 1. 背景与动机

当前 utest 判据只有一条：**testcase 级 result 行** `[  PASSED  ] [ result ] testcase (<name>)`（ADR-012 Decision 2）。
它只看最后 PASSED，不看中间关键业务字符串。

需求：对每个 utest case 做**更细的字符串检查**，即 result 行之外，再检查各 case 特有的业务输出关键字符串。

## 2. 现状

- 单文件模块：`ATS/modules/utest.py`（`@register("utest")`，一次动作 = 跑一个 testcase）
- 单文件协议：`ATS/drivers/utest_commands.py`（命令 / result 行正则 / 超时映射）
- 当前 scenario（`config/scenarios/utest.yaml`）有 **8 个 task**：efuse_test / filesystem / i2c_test / imu_test / pvt_auto_test / pvt_test / flash_xip_speed / flash_read
- `qspi_test` 已从 scenario 移除，`res/utestlog.txt` 仍有样本，`utest_commands.py` 超时映射仍保留

## 3. 已确认决策（D1~D7，实施以本节为准）

| # | 决策点 | 最终决定 |
|---|--------|---------|
| D1 | 细查与 result 行关系 | **叠加**：result 行优先，业务串为补充校验（语义见下） |
| D2 | 模块注册粒度 | **每 case 一个模块**（8 个独立 `@register` 模块，非单模块内部分派） |
| D3 | 目录命名 | **统一 `utest`**：`ATS/modules/utest/` + `ATS/drivers/utest/`（drivers 不用 utests） |
| D4 | flash_xip_speed 速率 | 先判「有速率打印」，`min_speed_kbs` 阈值做成配置项**默认 0（不校验）** |
| D5 | flash_read 无业务输出 | **文件得有**（模块 + commands 都建），但判据**暂只判 PASSED**（退回 result 行） |
| D6 | qspi_test | **本期不恢复**进 scenario（不建模块文件；超时表可保留映射，commands 预留说明） |
| D7 | 判据严格程度 | **值相等类严格 / 纯存在类宽松**（见 §4 逐项） |

### D1 叠加判据语义（必读）

叠加 = 「result 行」与「业务关键串」双重校验，优先级规则：

1. **result 行优先**：命中 `FAILED` → FAIL；`ERROR` → ERROR；`SKIPPED` → SKIP。**业务串不反向救回**（result 行 FAILED 但业务串齐全，仍 FAIL）。
2. result 行 `PASSED` 前提下，再校验业务关键串：
   - 业务串**齐全** → PASS
   - 业务串**缺失/不符** → FAIL（细查发现异常），detail 记录缺失的具体串
3. **无 result 行** → FAIL（同现状，兜底）。

> 即业务串只在「固件已汇总 PASSED」时作为补充校验，负责抓「PASSED 但内部步骤不完整」的情况。

## 4. per-case 关键字符串分析（来自 `res/utestlog.txt`）

> 纯文本为 ANSI 剥离后。`[I/utest]` 前缀与三档分隔符是框架固定串，非业务判据。
> 正则由 Code Agent 沉淀到 `ATS/drivers/utest/<case>_commands.py`（ADR-011 唯一来源）。
> 「类型」= 严格（值相等）/ 宽松（纯存在），按 D7。

### 4.1 efuse_test（2 unit，严格）

```
EFUSE uart_baud[63:32] = 0x000f4240 (expect 0x000f4240)
EFUSE flash_vendor[15:14] = 0x1 (expect 0x1)
```

- 判据：两条 `EFUSE ... = <val> (expect <val>)`，且 **`<val> == expect`**（同组回引正则）。
- 严格。

### 4.2 filesystem（1 unit，宽松）

```
[I/utest] emmc card mount to /emmc is success
[I/utest] Elm filesystem write test data is success!
[I/utest] Elm filesystem read test data is success!
```

> `[I/DFS.fs] the path:/emmc is not a mountpoint!` 是 mount 前合法中间态，不判失败。

- 判据：mount 成功 + write 成功 + read 成功 三行均出现。
- 宽松。

### 4.3 i2c_test（5 unit，严格）

```
i2c cpu wr: want 0x15 readback 0x15 PASS
i2c irq wr: want 0x15 readback 0x15 PASS
i2c dma wr: want 0x15 readback 0x15 PASS
i2c dma transmit: want 0x15 readback 0x15 PASS
i2c dma receive: expect 0x14 got 0x14 PASS
```

- 判据：5 个 sub-mode（cpu / irq / dma / dma transmit / dma receive）各一行，且**尾 `PASS`**；严格可校验 `want == readback`（receive 为 `expect == got`）。
- 严格（尾 PASS 必查，值相等可选加强）。

### 4.4 imu_test（1 unit，严格）

```
imu[N]: irq=M G(...)mDPS A(...)ug T=...   ×50 行
IMU: collected 50/50 frames, irq 73->122
```

- 判据：`IMU: collected 50/50 frames`，**`50/50` 帧数完整**；`irq 73->122` 为辅。
- 严格（50/50）。

### 4.5 pvt_auto_test（2 unit，宽松）

```
PVT0 auto monitor started (irq=69)   # 出现 2 次
PVT1 auto monitor started (irq=70)
```

- 判据：`PVT0 auto monitor started` 与 `PVT1 auto monitor started` 均出现（双通道都起）。
- 宽松。

### 4.6 pvt_test（3 unit，宽松）

```
PVT single voltage: 0.783V
PVT single temperature: 35.115C
PVT convenience: vol=0.778V, temp=34.878C
```

- 判据：`PVT single voltage:`、`PVT single temperature:`、`PVT convenience:` 三行均出现。
- 宽松。

### 4.7 flash_xip_speed（1 unit，宽松 + 可选阈值）

```
flash xip read speed: 6826 KB/s (size=1024 KB, time=150 ms)
```

- 判据：命中 `flash xip read speed: \d+ KB/s`（有速率打印）。
- 阈值 `min_speed_kbs` 为**配置项，默认 0（不校验）**；>0 时若速率 < 阈值判 FAIL。
- 宽松（默认只判存在）。

### 4.8 flash_read（1 unit，暂无业务输出）

```
（无任何业务打印，unit 名 jx_flash_test_read_unit 之后直接 result 行）
```

- 判据：**暂只判 PASSED**（result 行，D5）。模块文件与 commands 文件**均保留**，未来有日志再补业务串。
- 类型：N/A（当前）。

### 4.9 qspi_test（本期不恢复，预留说明）

```
1 lane fail!     # 合法中间态，严禁判失败
1 lane pass! / 2 lane pass! / 4 lane pass!
```

- D6：不恢复进 scenario、不建模块文件。`drivers/utest/_common.py` 超时表可保留 `qspi_test` 映射；commands 侧预留说明 `1 lane fail!` 为合法中间态，未来恢复时用。

## 5. 目录结构与模块命名（D2+D3）

```
ATS/modules/utest/                  # 取代 ATS/modules/utest.py（文件→包迁移）
├── __init__.py                     # import 各 case 模块触发 @register
├── base.py                         # utest 公共基类：result 行判据 + 叠加校验模板（D1 语义）
├── efuse.py                        # @register("utest_efuse")
├── filesystem.py                   # @register("utest_filesystem")
├── i2c.py                          # @register("utest_i2c")
├── imu.py                          # @register("utest_imu")
├── pvt_auto.py                     # @register("utest_pvt_auto")
├── pvt.py                          # @register("utest_pvt")
├── flash_xip_speed.py              # @register("utest_flash_xip_speed")
└── flash_read.py                   # @register("utest_flash_read")（暂只 result 行）

ATS/drivers/utest/                  # 取代 ATS/drivers/utest_commands.py（文件→包迁移）
├── __init__.py
├── _common.py                      # UTEST_RUN_COMMAND / UTEST_RESULT_RE / UTEST_TESTCASES 超时表
├── efuse_commands.py               # per-case 命令 + 业务关键串正则（ADR-011 唯一来源）
├── filesystem_commands.py
├── i2c_commands.py
├── imu_commands.py
├── pvt_auto_commands.py
├── pvt_commands.py
├── flash_xip_speed_commands.py
└── flash_read_commands.py          # 暂仅 result 行引用，无业务正则（D5）
```

**模块命名约定**：模块注册名 = `utest_<testcase 去 _test 后缀>`（如 `utest_efuse` ↔ efuse_test，`utest_filesystem` ↔ filesystem，`utest_i2c` ↔ i2c_test）。映射：

| 模块注册名 | testcase |
|-----------|----------|
| utest_efuse | efuse_test |
| utest_filesystem | filesystem |
| utest_i2c | i2c_test |
| utest_imu | imu_test |
| utest_pvt_auto | pvt_auto_test |
| utest_pvt | pvt_test |
| utest_flash_xip_speed | flash_xip_speed |
| utest_flash_read | flash_read |

**scenario 变化**（D2）：`config/scenarios/utest.yaml` 的 tasks 从 `- module: utest` + `override.testcase: <name>` 改为 8 个 `- module: utest_<case>`（testcase 名内置在模块，无需 override.testcase）。`override.timeout` 仍可单项覆盖。

## 6. 红线（实施必须遵守）

1. **ADR-011**：per-case 命令 / 判据 / 正则 / 超时唯一来源在 `drivers/utest/<case>_commands.py`，业务代码只 import，不内联协议字符串；`_common.py` 放公共协议。
2. **模块红线**：每个 case 模块 = 一次测试动作 + 参数接口，不写 for、不感知场景；跑哪些 case 由 scenario 逐项声明。
3. **哨兵 ≠ 业务完成**：`exec_sync` 的 expect 必须是真实业务字符串（result 行或业务关键串），不能是命令回显。
4. **不扫 fail/error 关键字**：`qspi_test` 的 `1 lane fail!`、`filesystem` 的 `not a mountpoint!` 均为合法中间态，必须显式传白名单 expect，避开 serial_console 默认 `_ERROR_RE`。
5. **D1 叠加语义**：result 行优先，业务串只做 PASSED 前提下的补充，不反向救回 FAILED。

## 7. 实施后文档动作（Document Agent 执行）

- [ ] 修订 ADR-012（Decision 1「单模块 utest」→「每 case 一模块」；Decision 2 补「叠加判据」语义；Impact 补记目录拆分）
- [ ] 更新 `01_architecture/module_design.md` utest 模块职责条目（注册粒度 + 目录结构变化）
- [ ] 更新 `05_handoff/next_step.md`（utest 细粒度判据状态推进）
- [ ] Code Agent 写 devlog（文件→包迁移留痕）

---

## 8. Code Agent 交接请求

> 本文件已人工拍板（§3 D1~D7）。请以 **Code Agent** 身份、按本节实施；文档动作（ADR-012 / module_design / handoff）由 Document Agent 在交付后处理，Code Agent 只写 devlog，不碰 architecture/ADR/handoff。

### Reason

utest 判据从「仅 result 行」细化为「result 行 + per-case 业务字符串叠加校验」（Level 3 架构变更，已由 Document Agent 出需求稿并获人工确认）。

### 实施步骤（按序）

**Step 1 — 迁移协议到 `drivers/utest/` 包**

删除 `ATS/drivers/utest_commands.py`，新建 `ATS/drivers/utest/`：

```
drivers/utest/
├── __init__.py
├── _common.py               # 原 utest_commands.py 内容整体迁入：
│                            #   UTEST_LIST_COMMAND / UTEST_RUN_COMMAND
│                            #   UTEST_RESULT_RE / UTEST_RESULT_ANY_RE
│                            #   UTEST_TESTCASES 超时表（保留 qspi_test 映射）
│                            #   UnknownTestcaseError / script_timeout_for
├── efuse_commands.py        # per-case 命令 + 业务关键串正则（§4）
├── filesystem_commands.py
├── i2c_commands.py
├── imu_commands.py
├── pvt_auto_commands.py
├── pvt_commands.py
├── flash_xip_speed_commands.py
└── flash_read_commands.py   # 暂无业务正则，仅引用 _common 的 result 行判据（D5）
```

- `qspi_commands.py` **不建**（D6）；`_common.py` 超时表保留 `qspi_test` 映射并在注释注明「`1 lane fail!` 为合法中间态，恢复时勿判失败」。
- 每 `*_commands.py` 只存协议常量（命令/判据/正则/超时/路径），不写 IO、不 import console/ftp/ctx（ADR-011）。

**Step 2 — 迁移模块到 `modules/utest/` 包**

删除 `ATS/modules/utest.py`，新建 `ATS/modules/utest/`：

```
modules/utest/
├── __init__.py        # from . import efuse, filesystem, i2c, imu, pvt_auto, pvt, flash_xip_speed, flash_read（触发 @register）
├── base.py            # 公共基类 UtestsBase(TestModule)：result 行判据 + 叠加校验模板（D1 语义）
├── efuse.py           # @register("utest_efuse")
├── filesystem.py      # @register("utest_filesystem")
├── i2c.py             # @register("utest_i2c")
├── imu.py             # @register("utest_imu")
├── pvt_auto.py        # @register("utest_pvt_auto")
├── pvt.py             # @register("utest_pvt")
├── flash_xip_speed.py # @register("utest_flash_xip_speed")
└── flash_read.py      # @register("utest_flash_read")
```

- 每个 case 模块 `run(ctx, console, params)`：发 `utest_run <testcase>`（testcase 名内置在模块常量，无需 override.testcase），复用 base 的叠加判据，传入该 case 的业务关键串正则。
- 模块红线：一次动作 + 参数接口，不写 for、不感知场景。

**Step 3 — 更新注册入口 `ATS/modules/__init__.py`**

- 现有一行 `from . import utest` 语义不变（utest 由 .py 变包后仍导入包，包内 `__init__.py` 触发各 case 注册），**确认删除旧 `utest.py` 后该行仍生效**，必要时在注释标注「utest 为包」。

**Step 4 — 改 scenario `config/scenarios/utest.yaml`**

tasks 从 8 个 `module: utest` + `override.testcase: <name>` 改为 8 个 `module: utest_<case>`（映射见 §5 表），`override.timeout` 单项覆盖能力保留。qspi_test 不加入。

**Step 5 — 叠加判据语义（D1，base.py 必须实现）**

```
exec_sync(UTEST_RUN_COMMAND.format(name=testcase), expect=UTEST_RESULT_RE, timeout=...)
  ├─ result 行 FAILED/ERROR/SKIPPED → 对应 TestResult（业务串不救回）
  ├─ result 行 PASSED →
  │    ├─ 业务关键串齐全 → PASS
  │    └─ 业务关键串缺失/不符 → FAIL（detail 列缺失串）
  └─ 无 result 行 → FAIL（兜底，同现状）
```

- 业务串校验仅在「固件已汇总 PASSED」时做补充；`qspi`/`filesystem` 的合法中间态（`1 lane fail!`、`not a mountpoint!`）绝不判失败。

**Step 6 — 写 devlog**

`docs/03_development/devlog/<YYYYMMDD>_<HHMM>_utest细粒度判据实施.md` 并更新 devlog README 索引。

### 红线（务必遵守）

1. ADR-011：协议唯一来源在 `drivers/utest/*_commands.py`，业务只 import。
2. 哨兵 ≠ 业务完成：`exec_sync` 的 expect 是真实业务字符串（result 行 / 业务串），非命令回显。
3. 显式传白名单 expect，避开 serial_console 默认 `_ERROR_RE` 误判合法中间态。
4. 不写 for、不感知场景；testcase 名内置模块，scenario 逐项声明。
5. flash_xip_speed 阈值 `min_speed_kbs` 为配置项，默认 0（不校验）；实现从 `config/modules/*.yaml` 读取，>0 才比对速率。

### 验收标准

- `python3 -m ATS.main --list-modules` 出现 8 个 `utest_*` 模块；`--list-scenarios` 识别 utest。
- `python3 -m ATS.main --scenario utest` 8 项按叠加判据跑通（离线可先用 `res/utestlog.txt` 样本 mock 串口自测）。
- 旧 `utest.py` / `utest_commands.py` 已删除，无残留 import。

### 交付后（Document Agent 接手）

Code Agent 完成并写 devlog 后，Document Agent 执行 §7 清单：修订 ADR-012、更新 module_design、推进 next_step。
