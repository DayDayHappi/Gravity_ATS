# ADR-011 收尾：emmc cd / 超时裸值提升为命名常量

- **日期**：2026-09-14
- **任务**：消除 ADR-011 串口协议集中化后仅剩的 1 个裸超时值。

## 问题描述

ADR-011 集中化整体通过检查后，`scenario_manager.py` 的 `preclean` 动作里 `cd /` 命令的超时仍是裸值 `timeout=5.0`，未与 `EMMC_CD_ROOT_COMMAND` 一并常量化，属协议集中化的最后收尾。

## 修复内容

1. `ATS/drivers/emmc_commands.py`：补一行超时常量 `EMMC_CD_ROOT_TIMEOUT = 5.0`（值与原裸值一致）。
2. `ATS/core/scenario_manager.py`：`preclean` 动作 `cd /` 改为
   `console.exec_sync(emmc_commands.EMMC_CD_ROOT_COMMAND, timeout=emmc_commands.EMMC_CD_ROOT_TIMEOUT)`。

## 验证结果

- `grep -n "EMMC_CD_ROOT_COMMAND, timeout=" ATS/` 无裸值匹配。
- `python3 -m py_compile ATS/drivers/emmc_commands.py ATS/core/scenario_manager.py` 通过。

## 还会再有吗

纯常量化、值不变，无新风险。
