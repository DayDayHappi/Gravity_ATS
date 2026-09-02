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
  - video 录像前暂时取消 `cam_set`（`if False:` 跳过，`TODO-TEMP-DISABLE-CAM_SET` 标记，后续恢复）
- 20260831 改动：
  - 日志目录按「场景/日期/运行时间戳」三级分层（devlog `20260831_1032`）：所有场景日志统一 `logs/<场景>/<日期>/<run_ts>/`（去掉中间冗余 logs 层），报告也按天分（normal→`reports/<日期>/`、非 normal→`logs/<场景>/report/<日期>/`），problem 记录归入 `logs/<场景>/problem/<run_ts>.log`
  - 新增独立 `download` 场景+模块（devlog `20260831_1419`）：仅从板端 FTP 下载、不做测试（`--scenario download`）
  - 修复 download 完整性校验 + 逐文件日志（devlog `20260831_1753`）：`ftp_client.download` 远端大小未知不静默成功（重查兜底+可疑失败），download 逐文件成功/失败日志带两端大小

```bash
python3 -m ATS.main --scenario normal --no-interactive-wifi            # 先通正常链路
python3 -m ATS.main --scenario stress --no-interactive-wifi            # 再通压测循环
python3 -m ATS.main --scenario stress_traverse_photo_mode --no-interactive-wifi  # 遍历全拍照模式压测（先小 repeat 冒烟）
python3 -m ATS.main --scenario download --no-interactive-wifi          # 纯录像跑完后手动下载板端文件
```

> **20260828 改动（commit `177976c`）**：
> - `stress_traverse_photo_mode.yaml` 参数调为冒烟值：`loop.count 20→200`、`photo.repeat 50→1`、`video.duration 180→20`、`rtmp.duration 600→20`（落地 P0 的「先小 repeat 冒烟」）。
> - `system.yaml` WiFi 默认值改为 `ftp_test_2_4G`/`12345678`（历史候选 SW-test-2.4G/ftp_hw_2_4g/G-Demo 已注释）。
> - 场景注释与参数脱钩**已完成**（commit `199ad95`）：头部与 `repeat` 行注释去掉写死的时长/次数，改为「自行按需配置」，纯注释不动参数。

## 🟡 P1 — H265 视频完整性检测模块（已实施·离线验证通过，待接线 + 真机）

需求已评审：[新增需求_H265视频完整性检测模块.md](../03_development/archive/新增需求_H265视频完整性检测模块.md)（Document Agent，2026-09-02，结论：与现有架构无冲突，按模块扩展机制实现，无需新 ADR）。

- **已实施**（devlog `20260902_1339`）：`ATS/modules/video_integrity.py` + `ATS/drivers/h265_validator.py` + `ATS/config/modules/video_integrity.yaml` + `ATS/config/scenarios/video_integrity.yaml`；`modules/__init__.py` 追加 import 触发 `@register`。核心验收点全部通过：不改 core、不碰 video.py、无新增 ctx 契约、模块内 deep-merge（§7）、argv list + timeout/kill 内存安全、单个 aggregate TestResult、manifest 去重（path+size+mtime_ns）、`.part` 过滤、Stage0 预检查。
- **离线验证已通过**（Document Agent 复核）：`py_compile` OK；`--list-modules`/`--list-scenarios` 识别；`trace_headers`/`showinfo` 正则与真实样本输出实测匹配；good.h265 → PASS，损坏样本 → FAIL（MISSING_REFERENCE）。
- **待决策**：normal/stress **未接线**（Code Agent 只交付 standalone 场景，`normal.yaml`/`stress.yaml` 未插入 `- module: video_integrity`）。原因：normal/stress 本身仍在「待真机验证」批次，插入未验证 task 有风险。需拍板：现在接线 vs 基础链路真机通过后再接线。
- **待真机**：Case B/C（normal/stress 录像后检测）未真机验证。
- **次要遗留（NON-BLOCKING）**：`_detect_missing_poc` 未用 `expected_gop_size` 校验实际 GOP 长度（`fixed_gop` confidence 未验证 GOP=30）；`_merge` 对 base 缺失的 deep-merge 段会静默丢弃（现状无害）；`NO_MATCHING_VIDEO` 已定义但从未产出。

## 🟡 P1 — 新增场景 stress_traverse_photo_mode_seq（待实施）

需求已整理：[新增场景需求_stress_traverse_photo_mode_seq.md](../03_development/archive/新增场景需求_stress_traverse_photo_mode_seq.md)。

- 新增 `ATS/config/scenarios/stress_traverse_photo_mode_seq.yaml`，实现「模式优先」顺序：
  auto×N → single×N → … → hdr_3×N（与 `stress_traverse_photo_mode.yaml` 的 round-robin 相对）。
- **纯配置，不改源码**：每模式一个 photo task + 单元素 `override.photo_modes` + `repeat`。
- `hdr_0~3` 模式名仍带 TODO-CONFIRM（与上个场景同源），真机一并核实。

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
