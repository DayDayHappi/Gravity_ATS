# 下一步（Next Step）

> 只保留未完成任务，按优先级。

## 🔴 P0 — 全部改动待真机验证

以下改动均已离线验证通过，**尚未真机验证**：

- Scenario 层重构 + 第四次交接 4 项改动（TX/RX 时间戳、exec_async 去哨兵、RTMP heartbeat、测试结束询问）
- 20260824 改动：normal 移除重复 ftp task、修复 `--no-interactive-wifi` 断链、WiFi 职责重划（ADR-008）、depends 字段清理（ADR-009）
- 20260825 改动：ADR-010 PreviewManager 单例播放器源码已实施（design 层 devlog 留痕，见 [P1 验收项](#🟡-p1--adr-010-previewmanager-待真机验收)）
- 20260826 改动：
  - video 判据修复：`Save Video Successful` → `Video recording completed successfully.` + 路径从 `r.clean` 累积缓冲扫描（devlog `20260826_2321`；与 photo 判据修复同类的对称 bug，实测路径分块截断致 flaky）
  - 新增场景 `stress_traverse_photo_mode.yaml`：photo task 用 `override.photo_modes` 遍历全部拍照模式（`auto/single/mfnr/hdr_0~3`），其余与 stress 一致；`hdr` 模式名待真机核实（TODO-CONFIRM，见场景文件注释）
- 20260827 改动：
  - video 启动判据加 f_index 兜底：`Record Start` → `Record Start|f_index\s*=` + 失败分支补发 `dfs_video_stop` 清理（devlog `20260827_0721`）
  - ~~video 录像前暂时取消 `cam_set`（`if False:` 跳过，`TODO-TEMP-DISABLE-CAM_SET` 标记，后续恢复）~~ 已于 20260907 恢复（devlog `20260907_1848`）
- 20260831 改动：
  - 日志目录按「场景/日期/运行时间戳」三级分层（devlog `20260831_1032`）：所有场景日志统一 `logs/<场景>/<日期>/<run_ts>/`（去掉中间冗余 logs 层），报告也按天分（normal→`reports/<日期>/`、非 normal→`logs/<场景>/report/<日期>/`），problem 记录归入 `logs/<场景>/problem/<run_ts>.log`
- 20260917 改动：
  - photo 单拍新增 3 个分辨率变体（devlog `20260917_1620`）：`photo_commands.py` 的 `PHOTO_MODES` 枚举 +3 条含空格模式名（`single 1080p/720p/480p`），`stress.yaml` photo task `override.photo_modes` 7→10 项；命令模板 `str.format` 天然支持含空格模式名，`photo.py` 零改动；已核实 report 消费方对含空格 `name`（`photo[single 1080p]`）无解析副作用。**待真机核实**：固件是否接受 `cam_set photo single <res>` 三 token 写法（TODO-CONFIRM，与 `hdr_0~3` 同类疑问）
  - `stress.yaml` photo task 1→10 拆分（devlog `20260917_1634`）：各单模式 + `repeat:1`，搭骨架支持每模式独立 repeat（后续调某模式只改对应 task 的 repeat）；纯配置零源码改动，repeat=1 时与拆分前行为等价。**待真机**
  - video 新增 480p_1 组合（devlog `20260917_1659`）：`video_commands.py` 补 profile（640×480 横屏，TODO-CONFIRM）+ 解除禁用（保留空常量防 NameError），`stress.yaml` 插 480p_1 task，`video_size_traverse.yaml` 仅改注释，`video.py` 零改动。**待真机 ffprobe 校准预期宽高**；另用户手改 stress.yaml 全部 video task 为 `repeat:1` + `duration:20`（原 sd1080p_0/1 repeat=10、duration=10），随本次留痕

```bash
python3 -m ATS.main --scenario normal --no-interactive-wifi            # 先通正常链路
python3 -m ATS.main --scenario stress --no-interactive-wifi            # 再通压测循环
python3 -m ATS.main --scenario stress_traverse_photo_mode --no-interactive-wifi  # 遍历全拍照模式压测（先小 repeat 冒烟）
```

> **20260828 改动（commit `177976c`）**：
> - `stress_traverse_photo_mode.yaml` 参数调为冒烟值：`loop.count 20→200`、`photo.repeat 50→1`、`video.duration 180→20`、`rtmp.duration 600→20`（落地 P0 的「先小 repeat 冒烟」）。**注**：后续 `a9bf449` 已将 video/rtmp duration 调为 66s。
> - `system.yaml` WiFi 默认值改为 `ftp_test_2_4G`/`12345678`（历史候选 SW-test-2.4G/ftp_hw_2_4g/G-Demo 已注释）。
> - 场景注释与参数脱钩**已完成**（commit `199ad95`）：头部与 `repeat` 行注释去掉写死的时长/次数，改为「自行按需配置」，纯注释不动参数。

## 🟡 P1 — H265 视频完整性检测模块（已实施·离线验证通过，待接线 + 真机）

需求已评审：[新增需求_H265视频完整性检测模块.md](../03_development/archive/新增需求_H265视频完整性检测模块.md)（Document Agent，2026-09-02，结论：与现有架构无冲突，按模块扩展机制实现，无需新 ADR）。

- **已实施**（devlog `20260902_1339`）：`ATS/modules/video_integrity.py` + `ATS/drivers/h265_validator.py` + `ATS/config/modules/video_integrity.yaml` + `ATS/config/scenarios/video_integrity.yaml`；`modules/__init__.py` 追加 import 触发 `@register`。核心验收点全部通过：不改 core、不碰 video.py、无新增 ctx 契约、模块内 deep-merge（§7）、argv list + timeout/kill 内存安全、单个 aggregate TestResult、manifest 去重（path+size+mtime_ns）、`.part` 过滤、Stage0 预检查。
- **离线验证已通过**（Document Agent 复核）：`py_compile` OK；`--list-modules`/`--list-scenarios` 识别；`trace_headers`/`showinfo` 正则与真实样本输出实测匹配；good.h265 → PASS，损坏样本 → FAIL（MISSING_REFERENCE）。
- **待决策**：normal/stress **未接线**（Code Agent 只交付 standalone 场景，`normal.yaml`/`stress.yaml` 未插入 `- module: video_integrity`）。~~原因：normal/stress 本身仍在「待真机验证」批次，插入未验证 task 有风险。需拍板：现在接线 vs 基础链路真机通过后再接线。~~ **已拍板**：20260907 先在 `stress_traverse_photo_mode.yaml` 接入（video→video_integrity→rtmp，devlog `20260907_2039`），normal/stress 暂不接。
- **待真机**：Case B/C（normal/stress 录像后检测）未真机验证。
- **次要遗留（NON-BLOCKING）**：`_detect_missing_poc` 未用 `expected_gop_size` 校验实际 GOP 长度（`fixed_gop` confidence 未验证 GOP=30）；`_merge` 对 base 缺失的 deep-merge 段会静默丢弃（现状无害）；`NO_MATCHING_VIDEO` 已定义但从未产出。
- **已新增（devlog `20260908_1847`）**：selection 值 `all_unchecked`（过滤已检 + 取全部，与 latest_unchecked 对称），解决 video task `repeat` 录多个文件时的「全检 + 跨 loop 不重复检」；现有 latest/all/latest_unchecked 行为不变。

## 🟡 P1 — utest 独立模块与场景（已实施·真机发现待修复项）

设计已定：[ADR-012](../02_design/decision_record/ADR-012-utest统一日志框架接入.md) + [ADR-013](../02_design/decision_record/ADR-013-串口探测指纹按场景分派.md)。

- **已实施**（Code Agent）：`drivers/utest_commands.py` + `modules/utest.py` + `config/modules/utest.yaml` + `config/scenarios/utest.yaml` + ADR-013 的 `serial_fingerprint` 透传。真机已跑通（utest 探测指纹 `msh >` 生效，9 项 testcase 均执行）。
- **待修复（Code Agent，本次）**：
  1. `pvt_auto_test` 脚本超时偏紧：`UTEST_TESTCASES` 里 10s，但实际 2 个 unit（`jx_pvt_auto_test` + `jx_pvt_dual_auto_test`）跑 10.2s → 哨兵超时。→ 超时调大（建议 20s，与 i2c 组对齐）。
  2. `utest.py` 误报「状态未知」：`exec_sync` 哨兵超时会直接失败返回（不看 expect），即使 result 行已出现；utest.py 的 `any_m` 分支把已匹配到的**白名单状态 `PASSED`** 误报为「状态未知」。→ 修正判据：`exec_sync` 失败后先用 `UTEST_RESULT_RE`（白名单）对 `r.clean` 重判，命中则按 status 出结果（result 行已出现=业务已完成，哨兵超时只是跑得慢），命中不了才走「真未知状态/无 result 行」分支。
  3. `utest.yaml` 去掉 `qspi_test` task（`UTEST_TESTCASES` 里的 qspi_test 映射可保留，未来想加回方便）。
  4. `utest.py` L46 去掉 `（脚本超时 {timeout:g}s）` 日志打印。
- 待真机补充：FAILED/ERROR/SKIPPED 的 result 行确切格式暂无样本（状态枚举已预留）。
- `utest_list` 本期不做（仅预留常量）。

> **配套（ADR-013）**：utest 固件 msh 提示符为 `msh >`（无斜杠），旧指纹 `msh\s*/>` 不匹配，按场景分派探测/就绪指纹。已实施：`utest.yaml` 的 `serial_fingerprint: utest` + `serial_console.py` 的 `_FINGERPRINT_SETS`/`_READY_RE_SETS` 映射 + `detect_port`/`SerialConsole` 可选参数 + `scenario.py` 的 `serial_fingerprint` 字段 + `scenario_manager.py` 透传。旧固件 default 路径逐字不动。

## 🟡 P1 — utest 细粒度判据（调查已存档·待决策恢复）

需求调查已存档：[新增需求_utest细粒度判据.md](../03_development/archive/新增需求_utest细粒度判据.md)（Document Agent，2026-09-17）。

- 已完成：逐 case 从 `res/utestlog.txt` 提取关键业务字符串（9 项），并给出目录结构草案。
- **阻塞（待人工拍板）**：D1 细查与 result 行「叠加/替代」（推荐叠加）；D2 模块注册「单模块内部分派/每 case 一模块」（推荐单模块）；D3 目录命名；flash_xip_speed 是否设速率阈值；flash_read 无业务输出是否纳入；qspi_test 是否恢复。
- **恢复条件**：人工确认上述决策点后，再交 Code Agent 实施（可能需修订 ADR-012）。

## 🟡 P1 — 新增场景 stress_traverse_photo_mode_seq（待实施）

需求已整理：[新增场景需求_stress_traverse_photo_mode_seq.md](../03_development/archive/新增场景需求_stress_traverse_photo_mode_seq.md)。

- 新增 `ATS/config/scenarios/stress_traverse_photo_mode_seq.yaml`，实现「模式优先」顺序：
  auto×N → single×N → … → hdr_3×N（与 `stress_traverse_photo_mode.yaml` 的 round-robin 相对）。
- **纯配置，不改源码**：每模式一个 photo task + 单元素 `override.photo_modes` + `repeat`。
- `hdr_0~3` 模式名仍带 TODO-CONFIRM（与上个场景同源），真机一并核实。

## 🟡 P1 — 新增场景 3k 录像压测（已实施·待真机）

需求已整理：[req_stress_traverse_photo_mode_3k.md](../03_development/archive/req_stress_traverse_photo_mode_3k.md)。**已实施**（devlog `20260909_1457`）：复制 `stress_traverse_photo_mode.yaml` 为 `stress_traverse_photo_mode_3k.yaml`，video task 加 override 强制 3k 录像。**待真机验证**。

> 注：commit `d7cee21` 引入新命令体系后，该场景 video override 已从裸 `"3k"` 迁移为
> `"3k_2"`（`cam_set video 3k 2`，见 `drivers/video_commands.py`）；裸 `"3k"` 会被新
> `video.py` 拒绝（ERROR）。

## 🟡 P1 — video_size_traverse 场景接入 H265 检测（已实施·待真机）

需求已整理：[req_video_size_traverse_add_integrity.md](../03_development/archive/req_video_size_traverse_add_integrity.md)。**已实施**（devlog `20260909_1940`）：在 11 个 video task 之后（photo 之前）插入一个 `video_integrity` task，override `input.selection: "all_unchecked"` + `empty_input_policy: "skip"`；头注释矛盾已修正；cleanup 补 `stop_stream` 兜底。**待真机验证**。

## 🟡 P1 — 串口协议集中化（ADR-011，已实施·待真机）

设计已定：[ADR-011](../02_design/decision_record/ADR-011-串口协议集中化.md)，Status=Accepted。

- 每模块串口命令/判据/超时/正则/路径统一沉淀到 `drivers/<module>_commands.py`（唯一来源），业务代码只 import 引用。
- **video 已完成**（`video_commands.py`，参照物）；photo/rtmp/ftp/wifi/emmc 五模块已迁移（5 个新文件）。
- **纯搬移不改值**：命令/判据逐字一致，发现可疑只加 `TODO-CONFIRM`，不在本次改协议语义。
- 边界：`*_commands.py` 只存协议常量，不写 IO/编排、不 import console/ftp/ctx；判据逻辑（ffprobe codec 判据、H265 三阶段诊断）不迁。
- **收尾已完成**（devlog `20260914_1321`）：`emmc_commands.py` 补 `EMMC_CD_ROOT_TIMEOUT = 5.0`，`scenario_manager.py` preclean 的 `cd /` 裸超时提升为命名常量（值不变），无残留裸超时。

## 🟡 P1 — 下载行为可配置 + 无网络场景（已实施·待真机）

需求已整理：[新增需求_下载行为可配置与无网络场景.md](../03_development/archive/新增需求_下载行为可配置与无网络场景.md)（Document Agent，2026-09-16）。**已实施**（devlog `20260916_0000`）。

- 已实施：photo/video 新增 `ftp_download` 开关（默认 true）；false 走纯拍摄/纯录像分支（不碰 FTP）；
  新增 `no_network.yaml`（prepare 去 wifi/ftp/preview，photo/video override `ftp_download: false`，
  去 rtmp/video_integrity）。
- **待真机**：无网络场景需真机确认 photo 存盘打印正则；有网络分支（默认 true）未跑真机回归。
- ~~`no_network.yaml` cleanup 冗余 `stop_stream`~~ 已修复（devlog `20260916_0001`，cleanup 只留 `close_serial`）。

## 🟡 P2 — ADR-010 PreviewManager 待真机验收

设计已定（[ADR-010](../02_design/decision_record/ADR-010-PreviewManager单例播放器.md)），源码已实施（devlog `20260825_0111_PreviewManager单例播放器实施.md`），**待真机验收**：

- 已实施：`ATS/drivers/preview_manager.py`（单例，含断流重连 wrapper）+ `config/modules/preview.yaml`；`rtmp.py` 移除全部 ffplay 逻辑；`scenario_manager.py` 新增 `preview_start`/`preview_stop`；`normal.yaml`/`stress.yaml` 补配置（`aging.yaml` 不启用）。
- 验收项：normal 全程 1 个 ffplay 窗口；stress repeat=3/loop 多轮不重复开窗、无残留进程；cleanup 正常关闭窗口。
- 已知遗留（见 devlog）：终端窗口模式 `killpg` 属 best-effort；`preview_required: true` 尚未闭环「影响整体结果」。

## 🟡 P3 — loop 语义局限

当前 loop 只能循环「整轮 tasks」，不支持「A 任务循环 N 次 + B 只跑 1 次」混合编排（目前靠 task.repeat + scenario.loop 两层凑合）。

## 🟡 P4 — 破坏性 CLI 变更

`--modules`/`--skip` 已移除，`--scenario` 成为主入口。旧文档命令全部失效，需同步。

## 🟢 P5 — RTMP 类型2 网络异常未覆盖

heartbeat 只能证明「板端编码线程活着」，证明不了「网络断但板端仍在编码」（f_index 持续但 ffprobe 收不到）。如需覆盖需补周期 ffprobe 复探。
