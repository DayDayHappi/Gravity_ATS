# ADR-012：utest 统一日志框架接入（新增 utest 独立模块与场景）

> **修订记录（2026-09-17）**：本 ADR 后续演进为「per-case 细粒度判据」——
> Decision 1 由「单模块 utest」改为「每 case 一模块」；Decision 2 由「唯一判据 result 行」改为
> 「result 行 + 业务关键串叠加」；Decision 5 的 `override.testcase` 改为「testcase 名内置模块」。
> 演进依据：[新增需求_utest细粒度判据.md](../../03_development/archive/新增需求_utest细粒度判据.md)
> （D1~D7 已人工拍板），实施 devlog `20260917_1824`，真机 2026-09-17 已跑通 8 项。
> 下文 Decision/Impact/Status 均为修订后的最终状态，原始决策历史见 git 与 devlog。

## Background

EVB 固件提供一套 `utest` 自检框架，覆盖 9 个板级检测项（efuse / filesystem / i2c / imu / pvt_auto / pvt / flash_xip_speed / flash_read / qspi）。所有检测项共用同一套日志框架（实测样例 `res/utestlog.txt`）：

```
utest_run <name>                                     # 同步阻塞命令，跑完才回 msh
[I/utest] [==========] [ utest    ] loop 1/1
[I/utest] [==========] [ utest    ] started
[I/utest] [----------] [ testcase ] (<name>) started
[I/utest] [==========] utest unit name: (<unit>)     # 每个 unit 一行
        ... 业务单元输出（各 testcase 特有） ...
[I/utest] [  PASSED  ] [ result   ] testcase (<name>)   # ★ 唯一可靠判据
[I/utest] [----------] [ testcase ] (<name>) finished
[I/utest] [==========] [ utest    ] 1 tests from 9 testcase ran.
[I/utest] [  PASSED  ] [ result   ] 1 tests.
[I/utest] [==========] [ utest    ] finished
```

框架级固定串（剥离 ANSI 后）：统一前缀 `[I/utest]`、三档节分隔符（`[==========]` utest 级 / `[----------]` testcase 级 / `[  PASSED  ]` 结果级）、固定对齐 tag（`[ utest    ]` / `[ testcase ]` / `[ result   ]`）、固定状态词（`started` / `finished` / `PASSED` / `FAILED`）。唯一变量是 `<name>` 与各 testcase 的业务单元输出。

## Problem

1. 现有框架以「功能模块」为单位（wifi / emmc / ftp / photo / video / rtmp），没有「固件板级自检」这类与 WiFi/FTP 无关、且由固件统一框架输出的检测通道。
2. utest 业务输出高度异构（efuse 数值比对、imu 逐帧数据、qspi `1 lane fail!` 中间态、flash_read 甚至无业务输出），若套用 `serial_console` 默认的 `_ERROR_RE` 判据会误判：`qspi_test` 的 `1 lane fail!` 是单元内合法中间态（最终 testcase 仍 PASSED）。
3. 固件已用 `[  PASSED  ] [ result   ] testcase (<name>)` 汇总好单元结果，脚本不应再扫 unit 级业务输出自行判 PASS/FAIL——那会重复实现固件已做好的判定，且难以覆盖所有异构输出。

## Decision

1. **单独封装为独立模块组 `utest`，独立场景 `utest`，不并入任何现有场景**（normal / stress / aging 等一律不动）。文件结构（修订后，D2/D3 每 case 一模块 + 目录统一 `utest`）：
   - `ATS/drivers/utest/` 包 — 协议唯一来源：`_common.py`（命令 / result 行正则 / 超时映射）+ 8 个 `<case>_commands.py`（testcase 名 + 业务关键串正则）
   - `ATS/modules/utest/` 包 — `base.py`（叠加判据模板）+ 8 个 case 模块，`@register("utest_<case>")`
   - `ATS/config/modules/utest.yaml` — 模块能力参数（含 `min_speed_kbs: 0` 速率阈值）
   - `ATS/config/scenarios/utest.yaml` — 独立场景（prepare 仅 `serial_init` + `preclean`，不依赖 WiFi/FTP）

2. **判据 = result 行（主）+ 业务关键串（补充）的叠加校验（D1）**，不扫 unit 级业务输出、不扫 `fail`/`error` 关键字：
   ```python
   UTEST_RESULT_RE = (r"\[\s*(?P<status>PASSED|FAILED|ERROR|SKIPPED)\s*\]"
                      r"\s*\[ result\s+\]\s*testcase\s*\(\s*(?P<name>\w+)\s*\)")
   ```
   - **result 行优先**：FAILED→FAIL、ERROR→ERROR、SKIPPED→SKIP，业务串**不反向救回**。
   - result 行 `PASSED` 前提下，再校验该 case 的业务关键串（`BUSINESS_RES`）：齐全→PASS；缺失/不符→FAIL（detail 列缺失串）。
   - 无 result 行 → FAIL（兜底）。
   - `exec_sync` 显式传 expect，`matched` 取 `group(1)`（= status），业务据此出 PASS/FAIL/ERROR。
   - 显式 expect 同时**避开** `_ERROR_RE` 默认兜底，解决 `qspi_test` 的 `1 lane fail!`、`filesystem` 的 `not a mountpoint!` 合法中间态误判。
   - 状态枚举 `PASSED|FAILED|ERROR|SKIPPED` 为**预留接口**：当前日志仅有 PASSED 样例，FAILED/ERROR/SKIPPED 的 result 行确切格式待真机补充，模块对未知状态走 `_error` 兜底（不猜测）。
   - 业务串严格度（D7）：**值相等类严格 / 纯存在类宽松**——efuse（`val == expect`）、i2c（`want == readback`/`expect == got`）、imu（`collected n/n`）用同组回引；filesystem / pvt_auto / pvt / flash_xip_speed 仅判存在；flash_read 暂无业务输出，暂只 result 行（D5）。

3. **命令面**：`utest_list`（列出 testcase + 固件 run timeout）与 `utest_run {name}`（跑单个 testcase）。`utest_run` 是同步阻塞命令（跑完回 msh），仍用 `exec_sync` + result 行 expect——哨兵只定界，result 行才是业务判据（符合红线「哨兵 ≠ 业务完成」）。

4. **每个 testcase 独立超时**：按 testcase 映射到脚本侧超时（固件 run timeout + 脚本余量），存 `drivers/utest/_common.py` 不可变映射，允许 `scenario override.timeout` 单项覆盖：
   | testcase | 固件 run timeout(s) | 脚本超时(s) |
   |---|---|---|
   | efuse_test / filesystem / imu_test / pvt_test | 1 | 10 |
   | i2c_test / flash_read / qspi_test | 10 | 20 |
   | pvt_auto_test | 1（实测约 10.2s） | 20 |
   | flash_xip_speed | 30 | 40 |

5. **模块红线对齐**：每个 `utest_<case>` 模块只实现「跑一个 testcase」这一动作，testcase 名内置模块（无需 `override.testcase`），跑哪些 case 由 `scenarios/utest.yaml` 的 tasks 逐项声明，模块内不写 for、不感知场景。判据逻辑收敛到 `modules/utest/base.py` 共享基类，8 个子类只设常量。

6. **`utest_list` 本期不做**（仅预留常量），不引入动态发现/核对流程。

## Alternative

- **并入 normal 场景**：把 9 项作为 normal 的 task。否决——utest 是板级自检，与 normal 的 WiFi/FTP/音视频链路无依赖，混入会破坏 normal 语义与 prepare 依赖（utest 不需要 ftp_ready / preview），且 imu/pvt 含噪声性数据不适合与常规链路串行老化。
- **业务串完全替代 result 行（D1=替代）**：放弃 result 行，各 case 只扫业务字符串。否决——固件已用 result 行汇总，是稳定契约，放弃后 `flash_read`（无业务输出）将无判据，且某 case 改打印格式即误判 FAIL。最终采纳**叠加**：result 行优先，业务串只在 PASSED 前提下做补充校验（抓「PASSED 但内部步骤不完整」）。
- **单模块内部分派（D2=单模块）**：保留一个 `@register("utest")` + `override.testcase` 分派。否决——需求要求每 case 独立封装，且每 case 独立模块便于未来单独调 case、单独补判据。最终采纳**每 case 一模块**（8 个 `utest_<case>`）。
- **动态 `utest_list` 发现 + 比对**：prepare 阶段发 `utest_list` 动态校验 testcase 清单与超时。否决（本期）——静态映射已够用，动态校验引入额外同步逻辑与不确定性；作为后续可选能力，本期不做。
- **放 yaml 存协议**：把 result 行正则/超时映射放配置。否决——协议是固件契约，遵循 ADR-011 单一来源原则，沉淀到 `drivers/utest/*_commands.py`（类型化 + 不可变映射），yaml 只放运行参数（testcase 名 / 可选 timeout 覆盖 / 速率阈值）。

## Impact

- 文件结构从「单文件」演进为「包」（每 case 一模块 + per-case 协议，D2/D3）：
  - `ATS/drivers/utest/`（`_common.py` + 8 个 `<case>_commands.py`）取代 `drivers/utest_commands.py`
  - `ATS/modules/utest/`（`base.py` + 8 个 case 模块）取代 `modules/utest.py`
- `config.py` `_MODULE_FILE_MAP` 补 8 个 `utest_<case>` → `utest` 映射（8 模块共用 `modules/utest.yaml`），否则 runner 阶段 `load_module_config` 报 ConfigError。
- `config/modules/utest.yaml` 补 `min_speed_kbs: 0`（flash_xip_speed 速率阈值，默认不校验）。
- 不改变 serial_console / runner / scenario 任何既有行为；`modules/__init__.py` 的 `from . import utest` 语义不变（utest 由 .py 变包后仍导入包）。
- 后续新增 utest 检测项：`drivers/utest/<case>_commands.py`（TESTCASE + BUSINESS_RES）+ `modules/utest/<case>.py`（继承基类）+ `_common.py` 超时映射 + `_MODULE_FILE_MAP` + `scenarios/utest.yaml` 增一行 task。
- 文档：本 ADR 登记到 `02_design/decision_record/README.md` 索引；`01_architecture/module_design.md` 新增 utest 模块职责条目；实施由 Code Agent 写 devlog（`20260917_1824`）。

## Status

Accepted（源码已实施并真机验证：2026-09-17 细粒度判据演进（每 case 一模块 + 叠加判据）真机跑通 8 项，见需求稿 `新增需求_utest细粒度判据.md` 与 devlog `20260917_1824`。早期真机发现待修复项 `pvt_auto_test` 超时偏紧、哨兵超时误报「未知」、去 qspi 均已解决，见 `05_handoff/next_step.md`。）

## 关联

- **ADR-013**：utest 固件 msh 提示符为 `msh >`（无斜杠），与旧固件 `msh />` 不同，需按场景分派串口探测/就绪指纹才能自动探测。utest 场景除本 ADR 的模块/判据设计外，还依赖 ADR-013 的 `serial_fingerprint: utest` 声明，二者配套实施。
