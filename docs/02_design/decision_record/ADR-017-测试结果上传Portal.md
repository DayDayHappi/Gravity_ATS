# ADR-017：测试结果上传 ATS Portal

## Background

ATS 已在本地产出结构化测试报告（`reports/<date>/<run_ts>/result.json`）与分层日志（`logs/<scenario>/<date>/<run_ts>/` 下的 `run.log` / `serial.log` / `power_switch.log` / `recovery.log`）。当前这些产物只落本地，需人工查看。

根目录新增协议文档 `ATS-Portal-Upload-Protocol-v1-20260929.md`，说明 ATS Portal（本机 `127.0.0.1:8080`）已具备接收脚本日志与结构化报告的能力，接口为「登记清单 → PUT 文件 → finalize」三步 HTTP 协议（Bearer 鉴权 + size/SHA-256 双重校验）。协议第 11 节明确：这是一份现有接收协议，采用它无需改网站后端。

## Problem

需要在**每次脚本运行结束后**，把本次运行的结果自动上传到 ATS Portal：

- 上传动作本身可配置（开关）。
- 上传哪些文件可配置。
- 上传失败不得影响 ATS 本身的测试结论（协议 §9.2 重试规则第 6 条）。

## Decision

### 1. 新增系统边界（Level 3，架构变更）

```
PC 脚本 ──HTTP(Bearer token, 本机明文)──> ATS Portal (127.0.0.1:8080)
```

属「运行结束后的结果上报」新机制，与既有串口/电源/RTMP 边界并列。引入此边界的原因：脚本不复制文件进网站目录，而是走 HTTP 三步归档接口。

### 2. 配置归属：`system.yaml` 新增 `upload` 段

上传属「本机是否具备上报能力」，环境级，类比 `power_switch.enabled`。放 `system.yaml`，**不放** modules/（非模块参数）、不放 scenarios/（非测试流程/循环）。

```yaml
upload:
  enabled: false                 # 上传开关，默认关（向后兼容，零影响）
  server: "http://127.0.0.1:8080"   # 服务地址
  token_file: ""                 # 空 = 默认 ~/.config/ats-portal/token
  timeout: 60                    # 单请求超时(秒)
  artifacts:                     # 上传清单（可配置，见 §3）
    - { name: "run.log", kind: "log" }
    - { name: "serial.log", kind: "log" }
    - { name: "power_switch.log", kind: "log" }
    - { name: "recovery.log", kind: "log" }
    - { name: "result.json", kind: "report" }   # 结构化报告，使网站展示用例 PASS/FAIL
```

token 读取优先级：`ATS_PORTAL_TOKEN` → `ATS_PORTAL_TOKEN_FILE` → `token_file` 配置 → 默认 `~/.config/ats-portal/token`。**token 不写日志、不进仓库**（协议 §2）。

### 3. 上传清单与 `kind`

`artifacts` 为可配置的文件清单，每项 `{name, kind}`。`kind` 取值协议 §4.2：`report` / `log` / `note` / `attachment`。

- 默认清单 = 4 个 log + 1 个 report（用户确认）。`result.json` 标记 `kind: report`，使网站能展示结构化用例结果（协议 §4.3：只传日志时网站状态为 `UNKNOWN`，无法展示 PASS/FAIL）。现 `reporter.py` 的 `_result_to_dict` 输出字段（name/module/status/elapsed_ms/message/detail/timestamp/scenario/cycle/rep）与协议 §7 完全一致，可直接复用，无需另造格式。
- 文件不存在（懒加载）：`run.log` / `serial.log` 在 `init_logger` 时即创建，恒存在；`power_switch.log` / `recovery.log` 为懒加载（仅当本次运行确实触发上下电/恢复才创建）。**上传时清单中不存在的文件应跳过（登记时只登记实际存在的文件）**，不得因缺文件导致上传失败。

### 4. 上传流程（三步协议，协议 §3–§6）

单次运行仅生成一个 `run_id`（`ats-` + `uuid4().hex`），流程：

1. `POST /api/v1/runs`：登记清单（`schema_version=1`、`run_id`、`mode`、`started_at`/`ended_at`/`execution_state`、`source`、`artifacts`，含每文件 size + sha256）。
2. 对每个存在的文件 `PUT /api/v1/runs/{run_id}/artifacts/{quote(name, safe='')}`：`Content-Type: application/octet-stream`，请求体 = 文件原始字节。
3. `POST /api/v1/runs/{run_id}/finalize`：确认归档，检查响应 `upload_state == "complete"` 才算成功。

### 5. 字段映射

| 协议字段 | 来源 |
|---------|------|
| `run_id` | 本次运行生成 `ats-` + uuid hex，重试复用（持久化） |
| `mode.id` | `scenario.name`（稳定，如 `recovery_validation`） |
| `mode.name` | `scenario.name`（初版 `name = id`，未来需中文显示名时再扩展） |
| `started_at` | 运行开始时刻（ISO 8601 带时区），需在 main 里记录 |
| `ended_at` | 运行结束时刻（ISO 8601 带时区） |
| `execution_state` | `completed`（正常结束，含用例 FAIL）／`aborted`（`env_error` 或 `ScenarioAbort` 中止）；未进入上传阶段（如配置加载失败）则不上传 |
| `source` | 初版留空 `{}`（多机器环境需要时再填 host/device） |

### 6. 挂接点与失败语义（红线）

- **挂接点**：`main.py` 在 `gen_report()` + `_record_test_problem()` 之后、`logger.close()` **之后**执行上传（协议 §2 要求先关闭/刷新日志文件再计算摘要）。上传读取的是已关闭的日志文件。
- **失败语义（红线）**：上传失败只 `logger.warn` 留痕，**不得改写 ATS 测试结论、不得影响退出码**（协议 §9.2 第 6 条）。
- **重试**：临时错误（网络超时/5xx/408/429）有限次数退避重试并复用同一 `run_id` 与清单；登记超时用原清单幂等重试（协议 §9.2）。
- **默认关闭**：`upload.enabled=false` 时零行为、零影响（不发起任何网络请求），向后兼容所有现有场景。
- **上传失败留痕（真机后补充）**：当前 `main.py` 顺序为 `logger.close()` 后才执行上传，此时 `_RUN_FP=None`，上传失败的 `logger.warn` 只打 stdout、不入 run.log。真机排查时发现 token 未配置导致的失败在 run.log 中无痕迹。计划新增懒加载 `upload.log` 独立留痕（见 known_issue.md，Code Agent 待实现）。

### 7. 实现落点（建议）

- 新增 `ATS/application/portal_upload.py`（或 `ATS/drivers/portal_upload.py`）：封装三步协议 + token 读取 + sha256/size 计算 + 重试，只依赖 `urllib`/标准库（不引入第三方 HTTP 库）。
- `main.py` 在 `logger.close()` 后调用上传入口，传入 `system_cfg.upload`、`log_root`/`report_root`/`run_ts`、`scenario.name`、`results` 与结束状态。
- 协议常量（路径/头/字段名）可集中到一个 `*_commands.py` 或上传模块内，遵守 ADR-011「协议唯一来源」精神（HTTP 协议非串口协议，但同样应集中、业务不内联 URL/头）。

## Alternative

- **不接 Portal，仅本地报告**：现状，无新增边界。
- **上传放 scenarios/*.yaml 按场景覆盖**：未采用——本需求未要求按场景区分上传内容，统一放 system.yaml 更简单；若未来需按场景差异化，再扩展。
- **引入第三方 HTTP 库（requests）**：未采用——标准库 `urllib` 足以覆盖三步协议，减少依赖。

## Impact

- **不破坏现有架构**：上传是运行结束后的一条独立数据流，不改 Scenario/Runner/Module/Driver 既有职责。全部能力默认关闭。
- **职责**：新增「结果上报」能力，由 main 收尾阶段调用，独立于测试链路；上传失败不影响测试结论。
- **预计修改**：`ATS/core/`（main.py 收尾接线）+ 新增 `ATS/application/portal_upload.py` + `config/system.yaml` 加 `upload` 段 + 单测。
- **原则上不修改**：Scenario/Runner/Module/Driver、`reporter.py`、`logger.py`（`result.json` 现有字段已兼容协议 §7）。

## Status

**已定稿·待实施**（Document Agent 定稿，Code Agent 待实现）。

## Acceptance Criteria

- **TC-UP-001** 关闭回归：`upload.enabled=false` 时零网络请求，退出码与报告同现状。
- **TC-UP-002** 仅日志归档：清单含 4 个 log（存在几个传几个），三步走完 `upload_state=complete`；`result.json` 未纳入时网站状态为 `UNKNOWN`。
- **TC-UP-003** 含报告归档：`result.json` 标记 `kind: report`，finalize 后网站展示用例 PASS/FAIL，`summary` 与 ATS 一致。- **TC-UP-004** 上传失败不影响结论：服务不可达/token 错误时，脚本退出码仍由测试结果决定，上传失败仅告警。
- **TC-UP-005** 懒加载文件缺失：本次运行未触发上下电/恢复时，`power_switch.log`/`recovery.log` 不存在，被跳过，归档仍成功。
- **TC-UP-006** 文件名编码：含中文/空格/`#` 的文件名经 `urllib.parse.quote(name, safe='')` 编码后 PUT 成功。
