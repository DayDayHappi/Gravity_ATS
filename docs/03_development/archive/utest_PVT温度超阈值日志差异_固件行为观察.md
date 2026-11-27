# utest PVT 温度超阈值日志差异（固件行为观察）

> 状态：**观察归档**（Document Agent，2026-11-27）。
> 性质：固件行为差异记录，**非 bug、不影响现有判据**。
> 来源：用户实测两份日志 —— `utest_pvt温度超过阈值情况.txt`（超阈值）与 `To_utest_res.txt`（正常）。

## 1. 现象

温度超过阈值时，`utest_run pvt_auto_test` 在 `PVTn auto monitor started` 之后会**大量追加** alarm 行：

```
PVT0 auto monitor started (irq=69)
PVT0 alarm: type=0 value=85120     ← 超阈值新增，约 100+ 行
PVT0 alarm: type=0 value=85497
...
PVT1 auto monitor started (irq=70)
PVT1 alarm: type=0 value=85309
...
[I/utest] [  PASSED  ] [ result   ] testcase (pvt_auto_test)   ← 仍 PASSED
```

正常温度下**无** alarm 行，仅两行 `PVTn auto monitor started`。

## 2. 差异对照

| 项 | 正常（`To_utest_res.txt`） | 超阈值（`utest_pvt温度超过阈值情况.txt`） |
|----|--------------------------|------------------------------------------|
| pvt_auto_test | 仅 `PVT0/PVT1 auto monitor started` | 同上 + 约 100+ 行 `PVTn alarm: type=0 value=NNNNN` |
| result 行 | `[ PASSED ] [ result ] testcase (pvt_auto_test)` | **同样 `[ PASSED ]`** |
| pvt_test 温度 | 83.985C / 84.364C / 54.476C | 84.742C / 85.309C |
| pvt_test 判据 | `PVT single temperature:` 存在 | 同（不捕获数值与否） |

## 3. 对现有判据的影响：无（逐点核实）

1. **业务关键串仍在**：`pvt_auto_commands.py` 判据为 `PVT0/PVT1 auto monitor started`，超阈值不改变该行 → D1 叠加判据照常命中。
2. **result 行仍 PASSED**：alarm 不改变固件汇总结论。
3. **`serial_console._ERROR_RE` 不命中**：该正则只含 `error|failed|fail|cannot|no such|not found|invalid(负向前瞻)|exception`，**不含 `alarm` / `type=0` / `value=`**。
4. **不落 `_ERROR_RE` 兜底**：utest 走 `exec_sync(expect=UTEST_RESULT_RE)`（`modules/utest/base.py:48`）显式白名单 expect。
5. **pvt_test 温度值判据宽松**：`PVT single temperature:` 只判存在，不校验数值。

## 4. 未来扩展线索（本期不做）

若后续需要「检测 PVT 温度是否超阈值」，信号源即该 `PVTn alarm: type=0 value=NNNNN` 行（正常时不出现）。

- 需先由固件侧确认：`value` 字段编码含义、`type=0` 的语义、阈值定义。
- 属**新增检测项**，按 ADR-011 需沉淀到 `drivers/utest/pvt_auto_commands.py`（`BUSINESS_RES` 追加 alarm 存在性判据）+ 可能新增 `DetectString`（ADR-014）。
- 当前**不实施**：用户 2026-11-27 明确「对判断没有影响」，仅要求知悉并留档。

## 5. 关联

- utest 判据机制：ADR-012（每 case 一模块 + 叠加判据）、ADR-011（协议唯一来源）、ADR-014（检测串集中化）。
- 判据实现：`ATS/drivers/utest/pvt_auto_commands.py` / `pvt_commands.py`、`ATS/modules/utest/base.py`。
