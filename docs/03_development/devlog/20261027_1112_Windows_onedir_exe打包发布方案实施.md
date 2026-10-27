# Windows onedir exe 打包发布方案实施（T1/T2/T3/T4/T5/T6/T7）

## Change

按 `docs/02_design/windows_cli_exe打包发布方案.md` 实施 7 项待办，使脚本可打包为 Windows 自包含控制台 exe，并保留「用户编辑 exe 同级 `config/`」能力。

1. **T1（核心）** `ATS/core/config.py`：`CONFIG_DIR` 改 frozen 感知。frozen 下优先 `sys.executable` 同级 `config/`（存在 `system.yaml` 才认），否则回退 `_MEIPASS/ATS/config` 内置只读备份；非 frozen 维持 `__file__` 派生逻辑。新增 `_INTERNAL_CONFIG_DIR` / `_resolve_config_dir()`。
2. **T2（核心）** 修 `config_dir` 透传缺口：
   - `ScenarioManager.run()` 设置 `ctx.config_dir = self.config_dir`。
   - `runner.py` L112、`scenario_manager.py` L450/451/514、`modules/ftp.py` L93 四处 `load_module_config` 改为 `getattr(ctx, "config_dir", None)` 透传。
   - `core/context.py` 补 `config_dir` 注释。
3. **T3（次要）** `ATS/application/portal_upload.py`：`_PROJECT_ROOT` frozen 感知（frozen→exe 同级，非 frozen→源码工程根），修正 token/ca_cert 相对路径锚定。
4. **T4** 新增 `AtsCli.spec`：onedir、控制台、`--collect-submodules ATS`、`--hidden-import jinja2/serial.tools.list_ports`、`--add-data`（配置源经 `ATSCLI_CONFIG_SRC` 指定）。
5. **T5** `scripts/build_windows_exe.py` 的 `_release_system_yaml`：发布版 `system.yaml` 收敛 `upload.enabled=false` 并移除 `server/token_file/ca_cert` 敏感项。
6. **T6** 新增 `scripts/build_windows_exe.py`：onedir spec 打包 + 发布目录组装（config/ + tools/ffmpeg 三件套 + 启动器 bat + 使用说明.txt）+ zip。
7. **T7** 新增 `scripts/build_windows_exe.py` 内置启动器生成（normal/stress/aging/no_network）与「使用说明.txt」。**手办文档 `docs/05_handoff/windows_cli_启动指南.md` 属 Document Agent 所有，未改，已产出 Document Agent Request。**

### 追加修复（Document Agent 反馈的 2 个发现）

- **发现 2 修复（🟡）**：内置 fallback 配置含敏感项。根因是 `--add-data` 直接打包源码 `ATS/config`（未收敛），而 T5 收敛发生在打包之后。修复：`AtsCli.spec` 的 `--add-data` 改从 `ATSCLI_CONFIG_SRC` 环境变量取配置源；`build_windows_exe.py` 在 `build_onedir` 前先用 `_release_system_yaml` 生成收敛 staging（`dist/_atscli_config_src`），传入 PyInstaller，打包后清理。发布 exe 内部 `_MEIPASS` 备份与 exe 同级 `config/` 均为收敛后配置。
- **发现 1 防御性降级（🔴 预存缺口，仅降级不重建）**：`ATS/tools/power_switch_stress.py` 经核实从未被 git 跟踪（无任何分支/备份历史），`--power-stress` 会 `ImportError` 崩溃。本次只做最小防御：`main.py` 的 `--power-stress` 分支捕获 `ImportError` 后打印明确错误并返回退出码 2，不静默、不伪造实现。**重建或摘除该工具交 Document Agent 决策**（涉及 handoff/interface_spec/test_case 文档同步，超 Code Agent 边界）。

### 追加（Code Agent Request，2026-10-27）

- `scripts/build_windows_exe.py` 的 `_write_launchers()` 场景元组新增 `("run_stress_NoFtp_NoRtmp", "stress_NoFtp_NoRtmp")`，发布目录生成 5 个启动器；`USAGE_TXT` 场景说明补 `stress_NoFtp_NoRtmp` 一行（无网络压测：photo×11 模式 + video×12 分辨率纯拍摄/录像，整轮循环 200 次，prepare 不挂 wifi_connect/ftp_ready/preview）。纯打包侧工具改动，不碰 ATS/ 源码与场景配置。

### 追加修复（🔴 严重回归，2026-10-27）

- **T5 收敛静默降级泄漏敏感项（fail-closed 修复）**：`_release_system_yaml` 在无 pyyaml 的解释器（如系统 Python）下运行会静默跳过收敛（只 WARN），导致发布包 `config/system.yaml` 与 `_internal/ATS/config/system.yaml` 重新含 `upload.enabled=true` + 内网 server/token_file/ca_cert。修复：`_release_system_yaml` 开头 fail-closed——`yaml is None` 时直接 `SystemExit` 并提示用含 pyyaml 的解释器（如 `.venv-cli\Scripts\python.exe`），不再静默降级；同时改写收敛头部注释为中文描述，避免 `grep token_file/ca_cert` 误匹配注释里的英文字面量。验证：系统 Python 无 yaml 下 `_release_system_yaml` 抛 SystemExit；`.venv-cli` 下收敛后 `upload.enabled=false` 且 `grep "10.1.64.183\|token_file\|ca_cert"` 无输出。

## Files

- `ATS/core/config.py`
- `ATS/core/runner.py`
- `ATS/core/scenario_manager.py`
- `ATS/modules/ftp.py`
- `ATS/core/context.py`
- `ATS/application/portal_upload.py`
- `ATS/main.py`（追加：--power-stress ImportError 防御性降级）
- `tests/test_windows_cli_frozen_config.py`（新增）
- `tests/test_recovery_runner.py`、`tests/test_recovery_third_round.py`（mock 适配 2 参签名）
- `AtsCli.spec`（新增；追加：ATSCLI_CONFIG_SRC 收敛配置源）
- `scripts/build_windows_exe.py`（新增；追加：打包前 staging 收敛）
- `.gitignore`（build/、dist/ 忽略）

## Reason

实现级路径解析与透传，不碰 `config → ScenarioManager → Runner → Module → Driver` 分层、不碰 ADR-011 协议集中化、不改任何模块判据。Level 1~2，无 ADR。

## Verification

- 新增离线单测 `tests/test_windows_cli_frozen_config.py` 6 例 PASS（T1 三态 + T2 显式 config_dir 优先 + T3 frozen 工程根）。
- 全量测试套件 `unittest discover -s tests -p "test_*.py"`：**69 例全 PASS**（含既有 63 例 + 新增 6 例）。
- `python -m ATS.main --list-scenarios` 列出 12 个场景；`--scenario no_network --dry-run` 通过。
- `T5 _release_system_yaml` 隔离验证：`upload.enabled=False` 且 `server/token_file/ca_cert` 已移除。
- `--power-stress`（缺实现文件）明确报错并返回退出码 2（不再 ImportError traceback）。
- 改动文件 `py_compile` 全部通过。

## Known limitation

- 未在本机执行真实 PyInstaller 打包（`.venv-cli` 无 PyInstaller，属打包机环境，脚本运行时自动检测并提示安装）。发布前需在打包机跑 `python scripts/build_windows_exe.py` 并做干净 Windows 冒烟。
- `ffmpeg 三件套` 需打包机补齐到 `tools/ffmpeg/` 或 PATH；目标机无 PATH 时缺失会 WARN（不中断）。
- `--power-stress` 仍不可用（实现文件缺失，仅从崩溃降级为明确报错）；重建或摘除待 Document Agent 决策。
