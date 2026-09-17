# ADR-012：utest 统一日志框架接入（新增 utest 独立模块与场景）

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

1. **单独封装为独立模块 `utest`，独立场景 `utest`，不并入任何现有场景**（normal / stress / aging 等一律不动）。新增 4 个文件，现有代码零改动：
   - `ATS/drivers/utest_commands.py` — 协议唯一来源（命令 / 判据 / 超时映射）
   - `ATS/modules/utest.py` — `@register("utest")` 模块，一次动作 = 跑一个 testcase
   - `ATS/config/modules/utest.yaml` — 模块能力参数
   - `ATS/config/scenarios/utest.yaml` — 独立场景（prepare 仅 `serial_init` + `preclean`，不依赖 WiFi/FTP）

2. **唯一判据 = testcase 级 result 行**（固件已汇总），不扫 unit 级业务输出、不扫 `fail`/`error` 关键字：
   ```python
   UTEST_RESULT_RE = (r"\[\s*(?P<status>PASSED|FAILED|ERROR|SKIPPED)\s*\]"
                      r"\s*\[ result\s+\]\s*testcase\s*\(\s*(?P<name>\w+)\s*\)")
   ```
   - `exec_sync` 显式传 expect，`matched` 取 `group(1)`（= status），业务据此出 PASS/FAIL/ERROR。
   - 显式 expect 同时**避开** `_ERROR_RE` 默认兜底，解决 `qspi_test` 的 `1 lane fail!` 误判。
   - 状态枚举 `PASSED|FAILED|ERROR|SKIPPED` 为**预留接口**：当前日志仅有 PASSED 样例，FAILED/ERROR/SKIPPED 的 result 行确切格式待真机补充，模块对未知状态走 `_error` 兜底（不猜测）。

3. **命令面**：`utest_list`（列出 testcase + 固件 run timeout）与 `utest_run {name}`（跑单个 testcase）。`utest_run` 是同步阻塞命令（跑完回 msh），仍用 `exec_sync` + result 行 expect——哨兵只定界，result 行才是业务判据（符合红线「哨兵 ≠ 业务完成」）。

4. **每个 testcase 独立超时**：按 testcase 映射到脚本侧超时（固件 run timeout + 脚本余量），存 `utest_commands.py` 不可变映射，允许 `scenario override.timeout` 单项覆盖：
   | testcase | 固件 run timeout(s) | 脚本超时(s) |
   |---|---|---|
   | efuse_test / filesystem / imu_test / pvt_auto_test / pvt_test | 1 | 10 |
   | i2c_test / flash_read / qspi_test | 10 | 20 |
   | flash_xip_speed | 30 | 40 |

5. **模块红线对齐**：`utest` 模块只实现「跑一个 testcase」这一动作，跑哪些 testcase 由 `scenarios/utest.yaml` 的 tasks 逐项声明（`override.testcase`），模块内不写 for、不感知场景。

6. **`utest_list` 本期不做**（仅预留常量），不引入动态发现/核对流程。

## Alternative

- **并入 normal 场景**：把 9 项作为 normal 的 task。否决——utest 是板级自检，与 normal 的 WiFi/FTP/音视频链路无依赖，混入会破坏 normal 语义与 prepare 依赖（utest 不需要 ftp_ready / preview），且 imu/pvt 含噪声性数据不适合与常规链路串行老化。
- **扫 unit 级业务输出判 PASS/FAIL**：为每个 testcase 写业务正则（如 `collected 50/50 frames`）。否决——固件已用 result 行汇总，脚本再判是重复实现；且异构输出（flash_read 无输出、qspi 有 fail! 中间态）无法用统一规则覆盖，维护成本高。
- **动态 `utest_list` 发现 + 比对**：prepare 阶段发 `utest_list` 动态校验 testcase 清单与超时。否决（本期）——静态映射已够用，动态校验引入额外同步逻辑与不确定性；作为后续可选能力，本期不做。
- **放 yaml 存协议**：把 result 行正则/超时映射放配置。否决——协议是固件契约，遵循 ADR-011 单一来源原则，沉淀到 `utest_commands.py`（类型化 + 不可变映射），yaml 只放运行参数（testcase 名 / 可选 timeout 覆盖）。

## Impact

- 新增 4 个文件（见 Decision 1），现有代码零改动：模块注册走 `base.py` 的 `@register` 全局表；配置加载走 `config.py` `_module_file` 的 `get(name, name)` 兜底（utest 不在 `_MODULE_FILE_MAP`，fallback 到 `modules/utest.yaml`）；场景与模块完全隔离。
- 不改变 serial_console / runner / scenario / config 任何既有行为。
- 后续新增 utest 检测项：仅在 `utest_commands.py` 超时映射 + `scenarios/utest.yaml` 增一行 task，不改代码逻辑。
- 文档：本 ADR 登记到 `02_design/decision_record/README.md` 索引；`01_architecture/module_design.md` 新增 utest 模块职责条目；实施后由 Code Agent 写 devlog。

## Status

Accepted（源码已实施：`drivers/utest_commands.py` + `modules/utest.py` + `config/modules/utest.yaml` + `config/scenarios/utest.yaml`，真机已跑通 9 项。真机发现待修复：`pvt_auto_test` 超时偏紧、哨兵超时后白名单状态被误报「未知」、去 qspi、去超时阈值日志，见 `05_handoff/next_step.md`。）

## 关联

- **ADR-013**：utest 固件 msh 提示符为 `msh >`（无斜杠），与旧固件 `msh />` 不同，需按场景分派串口探测/就绪指纹才能自动探测。utest 场景除本 ADR 的模块/判据设计外，还依赖 ADR-013 的 `serial_fingerprint: utest` 声明，二者配套实施。
