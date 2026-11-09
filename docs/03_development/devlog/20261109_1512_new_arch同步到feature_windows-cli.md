# new_arch 新功能与 BUG 修复同步到 feature/windows-cli

日期：2026-11-09
分支：`feature/windows-cli`（同步方向 new_arch → windows-cli，单向）
级别：Level 2 的搬运式同步（新增配置键 `photo_thumb_min_size_kb` / `photo_heif_min_size_kb`、driver 可选参数 `download(size_hint=)`），源码改动均为 new_arch 已验证提交，本分支只做移植与冲突合并。

## 问题描述

`feature/windows-cli` 分叉自 `eacb98f` 后长期未合入 new_arch 的后续提交，导致该分支缺少：

- 新场景 `3k_2`
- photo 模式执行顺序调整与末尾 `single 12m` 补齐
- BUG-008（缩略图 / HEIC 分档阈值）
- 下载重复 LIST 性能优化（`size_hint`）
- 对应文档与实测报告

同时该分支独有 Windows 平台抽象层、exe 打包、setup 脚本等改动，同步时不得被覆盖。

## 根因分析

两分支各自演进，`feature/windows-cli` 的 `portal_upload.py` 使用更完整的 `ca_cert` + `_build_ssl_context` + frozen 感知 `_PROJECT_ROOT` + `status=-1` 错误透传实现，而 new_arch 的 `209562d` 是较早的 `cert_file` + `_ssl_context` 设计。因此不能整提交 cherry-pick `209562d`（会把新实现回退成旧设计）。

## 修复内容（实际执行）

按序 cherry-pick 6 个提交（`209562d` 有意跳过）：

| 顺序 | 提交 | 结果 |
|------|------|------|
| 1 | `55f16e1` feat/3k_2 | 直接合入，新增 `ATS/config/scenarios/3k_2.yaml` |
| 2 | `b10310e` photo size 执行顺序 | 直接合入，`stress.yaml` photo 顺序调整 |
| 3 | `da7f1b3` 末尾加 12m | 直接合入，`photo_commands.PHOTO_MODES` + `single 12m`，stress 末尾 task |
| 4 | `3c0b63c` BUG-008 | 冲突 2 处（devlog README、known_issue），已手工合并 |
| 5 | `e3cd793` 消除下载重复 LIST | 直接合入（auto-merge devlog README） |
| 6 | `8f5a4d8` 纯文档 | auto-merge（known_issue 中 Windows 专有段落与 eMMC 范围外条目并存） |

冲突合并口径：

- `docs/03_development/devlog/README.md`：保留 windows-cli 的 20261027_1112 / 20261022_1317 / 20261019_1419 / 20261019_1319 四行，不引入 new_arch 的 20261019_1704（已被 windows-cli 方案 2-b 取代）；新增 20261105_1116、20261106_1129 两行。
- `docs/05_handoff/known_issue.md`：并入 BUG-008 已修复行与 `ftp_server` 幂等缺口行、eMMC 范围外行；**不并入** new_arch 的「ADR-017 自签名证书待修复」行（windows-cli 已由 `b77087f` 修复）；保留 windows-cli「Windows CLI 打包」段落与 `--power-stress` 过时点。

同步后本分支额外修正（new_arch 遗留的注释/测试缺陷，属本次同步的收尾）：

1. `stress.yaml` 顶部注释「11 个 task」→「12 个 task」，补执行顺序说明与「末尾 12m 规避下一轮切换失败」的既有实践注释；删除多余空行。
2. `3k_2.yaml` 顶部过时注释（photo/rtmp/3 轮与实际 task 不符）改为场景说明 + 3 条 TODO-CONFIRM（loop.count 200 vs 3 轮、cleanup 有 `power_switch_close` 但 prepare 无 `power_switch_init`、`preview.enabled: true` 但 prepare 无 `preview_start`）；清掉空行与引用不存在 repeat:10 的过时注释。**场景行为零改动。**
3. `tests/test_portal_upload.py`：`test_missing_token_raises` 从模块导入期绑定的 `PortalUploadError` 改为 `pu.PortalUploadError`。根因是本分支 `test_windows_cli_frozen_config` 会 `importlib.reload(portal_upload)` 重建异常类对象，导致后续 `assertRaises(旧类)` 失配（**该失败在同步前基线 `b5dfbdc` 上已存在**，非本次引入）。

## Files

- `ATS/config/scenarios/3k_2.yaml`（新增，含 TODO-CONFIRM 标注）
- `ATS/config/scenarios/stress.yaml`（photo 顺序 + single 12m + 注释修正）
- `ATS/drivers/photo_commands.py`（`single 12m`）
- `ATS/drivers/ftp_client.py`（`download(size_hint=)` + 保底复核）
- `ATS/modules/photo.py`（`_classify_image` / `_min_kb_by_kind` / `_verify_image` / `_list_jpgs` 返回 `[(name,size)]`）
- `ATS/modules/video.py`（下载传 `size_hint=sz`）
- `ATS/config/modules/photo.yaml`（三档阈值）
- `tests/test_photo_size_thresholds.py`（新增 10 例）
- `tests/test_ftp_download_size_hint.py`（新增 9 例）
- `tests/test_photo_heif.py`（改用 `_verify_image`）
- `tests/test_portal_upload.py`（异常类引用修正）
- `docs/**`：BUG-008 归档/修复记录、devlog 20261105_1116 / 20261106_1129、测试报告 20261105 压测耗时分析、module_design / test_case / test_strategy / known_issue / next_step / README 导航

## Verification

- `python -m unittest discover -s tests` → **Ran 90 tests, OK**（环境缺 `pyyaml` / `pyserial` 时会有 6 例报错，安装后全过；非代码问题）
- 交叉验证 `tests.test_windows_cli_frozen_config` + `tests.test_portal_upload` 组合 → OK（修正前该顺序必失败）
- `python -m ATS.main --list-scenarios` → 13 个场景，同时包含 `3k_2` 与 windows 专有 `stress_NoFtp_NoRtmp`
- `--scenario stress --dry-run` → EXIT=0；`--scenario 3k_2 --dry-run` → EXIT=0；`--scenario stress_NoFtp_NoRtmp --dry-run` → EXIT=0
- 逐文件比对：`photo.py` / `ftp_client.py` / `video.py` / `photo_commands.py` / `photo.yaml` / 两个新测试 / `test_photo_heif.py` / `3k_2.yaml` 与 new_arch 一致（`3k_2.yaml` 除注释外一致）
- 确认 windows-cli 独有实现未被回退：`portal_upload._PROJECT_ROOT` frozen 感知、`_build_ssl_context`、`status != -1` 错误透传、`system.yaml` 的 `ca_cert` 键均在位

## Known limitation

- 全部为离线验证；`stress` / `3k_2` / `stress_NoFtp_NoRtmp` 仅 dry-run，未真机执行。
- `3k_2.yaml` 的 3 条 TODO-CONFIRM（轮次语义、power_switch init 配套、preview_start 缺失）**原样保留**，需人工拍板后再改。
- `ftp_server` 幂等判据缺失（`already running`）仍为待修复项，未纳入本次同步。
- 未执行的可选 delta：`ATS_PORTAL_CA_CERT` 环境变量覆盖 + `~/ats/cert.pem` 默认回退（new_arch 有、本分支无），待用户拍板。

## 经验沉淀

跨分支同步「按提交粒度判定」比「按文件覆盖」安全：先看该提交在本分支是否已被更完整实现取代，再决定 cherry-pick 还是仅补 delta。测试文件若引用模块级异常类/常量，而同仓另有 `importlib.reload` 用例，应按模块属性引用（`pu.XxxError`）而非导入期绑定。
