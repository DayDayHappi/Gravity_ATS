# Code Agent 任务单：`stress.yaml` 的 photo task 替换为实测可用命令

> 由 Document Agent 出具，交 Code Agent 执行。
> **状态：已就绪，可实施**（依据 2026-11-20 真机实测）。
> 作用分支：`feat/windows_rebuild_app_arch`。
> 变更级别：**Level 1**（纯场景配置，不改源码/协议/接口，**无需新 ADR**）。
> 依据：[test_report_20261120_photo_mode_size全枚举.md](../../04_testing/test_report_20261120_photo_mode_size全枚举.md)、[ADR-018](../../02_design/decision_record/ADR-018-photo参数结构化.md)、并行任务单 [code_task_photo_only收缩为可用命令.md](code_task_photo_only收缩为可用命令.md)。

## 1. 目标

把 `ATS/config/scenarios/stress.yaml` 中**全部原有 photo task 删掉**，替换为**实测可拍成功且本轮纳入的 12 条命令**。

## 2. 背景

- 真机实测 42 组合：15 可拍、12 被拒、10 `cam open failed`、5 `fcov` 有锁死风险。详见 test_report。
- 用户另决定「暂不支持」3 条实测可用项（`single 3m`、`heif 8m`、`heif 720p`）→ 可用集合 15→**12**。
- 本次把这 12 条放进 `stress.yaml`，**删除 stress 里原有的全部 photo task**（原 11 个，见 §3.1）。

**12 条命令（= 最终纳入的拍照集）**：

```
cam_set photo auto   size 12m
cam_set photo single size 12m / 1080p / 720p / 480p
cam_set photo mfnr   size 12m
cam_set photo hdr    size 12m
cam_set photo heif   size 12m / w8m / 3m / 1080p / 480p
```

## 3. 精确改动

### 3.1 删除范围

`ATS/config/scenarios/stress.yaml` 现 L17–72（`# photo 按模式拆成 12 个 task…` 注释起，到 `photo_modes: [{mode: heif}]` 止）**整段删除**，共 11 个 photo task（hdr 0~3 / mfnr / auto / single / single 1080p / 720p / 480p / single 12m / heif），及其顶部注释。

> 其余 task（video×6、video_integrity、rtmp）与 prepare/loop/cleanup **一律不动**。

### 3.2 新插入的 photo task（12 个，单元素 photo_modes + repeat: 1）

**保留 stress 既有设计**：仍按「每模式一个 task + 单元素 `photo_modes` + 独立 `repeat`」拆分（便于后续单独调某条 repeat 次数，符合「重复由 Scenario/Runner 驱动」红线）。

**顺序沿用既有实践**：`hdr → mfnr → auto → single → heif`；`single` 组内 **`12m` 放末位**（沿用「末尾补 12m 规避下一轮切换失败」的既有实践，勿随意调整）。

```yaml
    # photo 实测可用命令（2026-11-20 真机验证；ADR-018 结构化 {mode, size}）。
    # 已删除原 42 枚举中的不可用项：auto/mfnr/hdr 仅 12m；single 去掉 3m/8m/w8m；
    # heif 去掉 8m/720p（暂不支持）；fcov 整体排除（持续取流会锁死板子）。
    # 顺序沿用：hdr → mfnr → auto → single → heif；single 12m 置末位（规避下一轮切换失败）。
    - module: photo
      repeat: 1
      override:
        photo_modes: [{mode: hdr, size: 12m}]
    - module: photo
      repeat: 1
      override:
        photo_modes: [{mode: mfnr, size: 12m}]
    - module: photo
      repeat: 1
      override:
        photo_modes: [{mode: auto, size: 12m}]
    - module: photo
      repeat: 1
      override:
        photo_modes: [{mode: single, size: 1080p}]
    - module: photo
      repeat: 1
      override:
        photo_modes: [{mode: single, size: 720p}]
    - module: photo
      repeat: 1
      override:
        photo_modes: [{mode: single, size: 480p}]
    - module: photo
      repeat: 1
      override:
        photo_modes: [{mode: single, size: 12m}]
    - module: photo
      repeat: 1
      override:
        photo_modes: [{mode: heif, size: 12m}]
    - module: photo
      repeat: 1
      override:
        photo_modes: [{mode: heif, size: w8m}]
    - module: photo
      repeat: 1
      override:
        photo_modes: [{mode: heif, size: 3m}]
    - module: photo
      repeat: 1
      override:
        photo_modes: [{mode: heif, size: 1080p}]
    - module: photo
      repeat: 1
      override:
        photo_modes: [{mode: heif, size: 480p}]
```

> 12 条明细：`hdr-12m`、`mfnr-12m`、`auto-12m`、`single-{1080p,720p,480p,12m}`、`heif-{12m,w8m,3m,1080p,480p}`。

## 4. 验收标准

### 离线

1. `stress.yaml` 中 `module: photo` 的 task 数 = **12**；
2. 不含任何 `fcov`、不含 `{mode: <auto|single|mfnr|hdr>, size: <8m|w8m|3m>}`、不含 `{mode: heif, size: <8m|720p>}`；
3. `grep -c "num:" stress.yaml` 在 photo 段为 0（新配置统一用 `size`，不用 `num`）；
4. `python3 -m ATS.main --scenario stress --dry-run` exit 0；
5. 其余 task（video×6 / video_integrity / rtmp）计数与改动前一致。

### 真机（可选）

photo 段 12 条全回 `Capture completed successfully.`，无 `does not support` / `cam open failed` / 板子卡死。

## 5. 明确不做

- ❌ 不改 `stress.yaml` 的 prepare / loop / cleanup / video / video_integrity / rtmp。
- ❌ 不改 `ATS/drivers/photo_commands.py`、`ATS/modules/photo.py`（属 ADR-018 任务单 `code_task_photo_size关键字显式化.md` 范围）。
- ❌ 不改 `photo_only.yaml`（另有 [code_task_photo_only收缩为可用命令.md](code_task_photo_only收缩为可用命令.md)）。
- ❌ 不改其它场景（`recovery_validation` / `stress_NoFtp_NoRtmp` / traverse 等，另案）。
- ❌ 不修改 `docs/`（Document Agent 负责）。

## 6. 交付要求

1. 若随分支提交，按工程红线 1 在 `docs/03_development/devlog/` 新建记录并更新索引（纯配置改动；若认为无需 devlog，在提交信息说明）；
2. 真机若 12 条中有未预期 FAIL，**先回报**，不要自行改判据或凑参数。

## 7. 备注

- 本任务单与 `code_task_photo_only收缩为可用命令.md` 是**同一批 12 条命令**在两个场景（`stress` / `photo_only`）的落点；可一并实施。
- **待用户拍板（不阻塞）**：`8m/w8m` 是否永久跳过、`fcov` 是否单列独立场景、"暂不支持"3 条（`single 3m`/`heif 8m`/`heif 720p`）何时恢复 —— 见 test_report §七 TODO-CONFIRM。
