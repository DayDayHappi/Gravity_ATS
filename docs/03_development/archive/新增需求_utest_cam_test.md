# 新增需求：utest 新增 cam_test 检测项

> 状态：**需求已定稿**（Document Agent，2026-11-27），待 Code Agent 实施。
> 角色边界：本文档属 `docs/03_development/archive/`（需求规格）。Code Agent 只实现 `ATS/drivers/utest/` + `ATS/modules/utest/` + `ATS/core/config.py` + `ATS/config/scenarios/utest.yaml` + `docs/03_development/devlog/`；**不改架构 / ADR / handoff**（Architecture/ADR/handoff 由 Document Agent 在交付后更新）。
> 关联：ADR-012（utest 每 case 一模块 + 叠加判据）、ADR-011（协议与判据分离）、ADR-013（串口指纹）。

---

## 0. 评审结论（先读这里）

- **纯扩展，无架构冲突**：完全复用现有 utest 扩展机制（`@register("utest_<case>")` + `drivers/utest/<case>_commands.py` + `UtestCaseModule` 叠加判据基类），不改 Scenario/Runner/Module/Config/Driver 边界。
- **不需要新 ADR**：ADR-012 已定义「每 case 一模块」与「result 行 + 业务串叠加判据」；本需求只是按该机制再加一个 case。
- **不碰 `echo` 哨兵**：`utest_run` 仍走 `exec_sync`（固件已恢复 `echo`），本次不动串口层。

---

## 1. 背景

utest 固件新增 `cam_test`（摄像头 bring-up 自检），已真机实测跑通。需将其接入 `utest` 场景，按现有 D1 叠加判据规则判定 PASS/FAIL。

---

## 2. 实测日志分析（用户实测，2026-11-27）

命令：`utest_run cam_test`，实测耗时 `392937 → 400080` ≈ **7.1s**。

**成功判据（两层，缺一不可）**：

1. **result 行**（主判据，现成基类已处理）：
   ```
   [I/utest] [  PASSED  ] [ result   ] testcase (cam_test)
   ```
2. **业务关键串**（D1 叠加，本次需新增）：
   ```
   sif0  [0xf9000254]=0x0000030c (expect 0x0000030c) ok
   ```
   （ANSI 剥离后；日志中该行有前导 `  ` 与行内多空格，正则需容忍空白。）

> 说明：同段还有 `csi0/ph yo0/fe0` 等寄存器 dump 行，但**只有 sif0 行带 `(expect ...) ok`**，是唯一需校验的业务串。故判据锚定 `sif0 [...]=(...) (expect ...) ok` 结构。

`utest_list` 中 cam_test 的 `[run timeout]:10` → 脚本超时取 **20s**（与 `i2c_test`/`flash_read` 的「固件 10s 组 → 脚本 20s」一致；实测 7.1s 留足余量）。

---

## 3. 判据设计（D1 叠加语义，与 efuse/i2c 一致）

- **result 行 PASSED** 由 `modules/utest/base.py` 的 `UtestCaseModule` 现成处理（`UTEST_RESULT_RE`），**无需新写**。
- **业务串**用**严格值相等**（D7 值相等类）：`= <val> (expect <val>)` 用同组回引 `\1`，保证 `0x0000030c == 0x0000030c`。
- 仅当 result 行 PASSED 且业务串命中 → PASS；业务串缺失/值不等 → FAIL（基类 `_collect_missing` 自动处理）。
- **不扫 `fail`/`error` 关键字**（沿用红线：显式传白名单 expect）。

> **用户已拍板（2026-11-27）**：
> 1. `sif0 [0xf9000254]` 地址与期望值 `0x0000030c` 为该 case **固定值**（正则可硬编码）；
> 2. **执行强校验**（回引 `\1`，`val == expect`）；
> 3. cam_test 在 `utest.yaml` **放在最后一条** task。

**确定正则**（`drivers/utest/cam_commands.py`）：

```python
TESTCASE = "cam_test"

# 业务关键串正则（D1 叠加：result 行 PASSED 前提下命中才 PASS）。
# 严格（D7 值相等类）：= <val> (expect <val>) 用同组回引 \1 保证 val == expect。
BUSINESS_RES = [
    r"sif0\s+\[0xf9000254\]=(0x[0-9a-fA-F]+)\s+\(expect\s+\1\)\s+ok",
]
```

> 对 `sif0  [0xf9000254]=0x0000030c (expect 0x0000030c) ok` 命中；若 expect 值与实测值不等则不匹配（严格，用户拍板执行强校验）。地址 `0xf9000254` 与期望值 `0x0000030c` 为该 case 固定值。

---

## 4. 精确改动点（6 处，全部对齐现有 case 模式）

| # | 文件 | 改动 |
|---|------|------|
| 1 | **新增** `ATS/drivers/utest/cam_commands.py` | 上述 `TESTCASE` + `BUSINESS_RES`（ADR-011 唯一来源，只存常量，不写 IO/不 import console/ftp/ctx） |
| 2 | **新增** `ATS/modules/utest/cam.py` | 见下方类模板 |
| 3 | `ATS/modules/utest/__init__.py` | 追加 `from . import cam  # noqa: F401` |
| 4 | `ATS/core/config.py` `_MODULE_FILE_MAP` | 追加 `"utest_cam": "utest"` |
| 5 | `ATS/drivers/utest/_common.py` `UTEST_TESTCASES` | 追加 `"cam_test": 20.0`（固件 10s 组 → 脚本 20s） |
| 6 | `ATS/config/scenarios/utest.yaml` | tasks **末尾追加** `- module: utest_cam`（用户拍板：放最后一条） |

**`modules/utest/cam.py` 模板**（照 `efuse.py`）：

```python
"""cam_test 模块：sif0 寄存器 IRQ 状态业务判据（ADR-011/ADR-012）。"""
from ..base import register
from .base import UtestCaseModule
from ...drivers.utest import cam_commands as commands


@register("utest_cam")
class CamModule(UtestCaseModule):
    testcase = commands.TESTCASE
    business_res = commands.BUSINESS_RES
```

> 模块注册名约定 `utest_<testcase 去 _test 后缀>` → `cam_test` → `utest_cam`。

---

## 5. 红线（实施必须遵守）

1. **ADR-011**：命令/判据/超时唯一来源在 `drivers/utest/cam_commands.py` 与 `_common.py`，业务只 import。
2. **模块红线（ADR-007）**：每个 case 模块 = 一次测试动作，不写 for、不感知场景；跑哪些 case 由 scenario 逐项声明。
3. **哨兵 ≠ 业务完成**：`utest_run` 的 expect 是真实业务串（result 行），非命令回显。
4. **不扫 fail/error 关键字**：显式传白名单 expect 避开 `serial_console` 默认 `_ERROR_RE`。
5. **不改 core/serial 层**：本次仅新增一个 case，禁止顺手改 `serial_console.py` / `runner.py` / `base.py`（`UtestCaseModule` 无需改）。

---

## 6. 验收标准

- `python3 -m ATS.main --list-modules` 出现 `utest_cam`。
- `python3 -m ATS.main --scenario utest --dry-run` 通过（配置/注册无错）。
- `utest.yaml` 的 tasks **最后一条**为 `- module: utest_cam`（用户拍板）。
- 离线单测（建议新增，仿 `tests/test_photo_size_thresholds.py` 风格）：
  - `cam_commands.BUSINESS_RES[0]` 对实测行 `sif0  [0xf9000254]=0x0000030c (expect 0x0000030c) ok` **命中**；
  - 对不等值行 `sif0  [0xf9000254]=0x0000030c (expect 0x0000030d) ok` **不命中**（验证强校验语义）。
- 真机 `--scenario utest`：cam_test 项 PASS，日志含 result 行 PASSED + sif0 业务串。
- 旧行为零回归：其余 utest 项不受影响。

---

## 7. Devlog（Code Agent 交付时）

新建 `docs/03_development/devlog/<YYYYMMDD>_<HHMM>_utest新增cam_test.md` 并更新 devlog README 索引，记录：实测量 + 新增文件 + 判据正则 + 验证结果（区分 PASS/FAIL/NOT RUN，未真机不得写 PASS）。

---

## 8. 交付后 Document Agent 动作（不在 Code Agent 范围）

Code Agent 完成后由 Document Agent 执行：

- [ ] `01_architecture/module_design.md`：utest 模块组「8 个 `utest_<case>`」→「9 个」（§24 表 + §143 段落，同步标注 cam_test）。
- [ ] `02_design/decision_record/ADR-012`：case 清单补 `cam_test`，注明「2026-11-27 新增」。
- [ ] `04_testing/test_case.md`：补 cam_test 用例行（若列 utest 明细）。
- [ ] `05_handoff/next_step.md` / `known_issue.md`：如需登记真机验证状态。

---

## 9. 附带事实（本次不处理，供 Code Agent 知悉）

- `utest_list` 当前为 **9 项**：`cam_test / efuse_test / i2c_test / imu_test / pvt_auto_test / pvt_test / flash_xip_speed / flash_read / qspi_test`。
- **`filesystem` 不在固件清单**：用户已手动从 `utest.yaml` 移除（`#- module: utest_filesystem` 注释态），本次不处理。`_common.py` 的 `UTEST_TESTCASES` 是否保留 `filesystem` 映射由 Code Agent 自行判断（保留无副作用）。
- `qspi_test` 仍按 D6「本期不加」。
