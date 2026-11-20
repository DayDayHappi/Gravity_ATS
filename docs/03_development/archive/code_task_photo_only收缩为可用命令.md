# Code Agent 任务单：`photo_only.yaml` 收缩为实测可用命令

> 由 Document Agent 出具，交 Code Agent 执行。
> **状态：已就绪，可实施**（依据 2026-11-20 真机实测，见 §2）。
> 作用分支：`feat/windows_rebuild_app_arch`。
> 变更级别：**Level 1**（纯场景配置，不改源码/协议/接口，**无需新 ADR**）。
> 依据：[test_report_20261120_photo_mode_size全枚举.md](../../04_testing/test_report_20261120_photo_mode_size全枚举.md)、[ADR-018](../../02_design/decision_record/ADR-018-photo参数结构化.md)。

## 1. 目标

把 `ATS/config/scenarios/photo_only.yaml` 的 `photo_modes` 从「42 组合全枚举」**收缩为 12 条**：
- 排除固件不可用/有毒的（12 被拒 + 10 open 失败 + 5 `fcov`）；
- 再按用户 2026-11-20 决定，**暂不支持** 3 条实测可用项（`single 3m`、`heif 8m`、`heif 720p`）。

## 2. 背景（真机实测结论，2026-11-20）

逐条实测 42 组合（详见 test_report）：

| 结果 | 条数 | 组合 |
|---|---|---|
| ✅ 可拍成功 | **15** | `single`×{12m,3m,1080p,720p,480p}、`auto/mfnr/hdr`×{12m}、`heif`×全 7 |
| ⛔ SET 被拒 | 12 | `auto/mfnr/hdr`×{3m,1080p,720p,480p}（`does not support <mode> (supported: single)`） |
| ❌ cam open failed | 10 | `auto/single/mfnr/hdr/fcov`×{8m,w8m}（ATF `ret=1541`） |
| ⚠️ 持续取流+锁死板子 | 5 | `fcov`×{12m,3m,1080p,720p,480p}（**只能断电恢复**） |

**排除理由**：`8m/w8m` 小概率整板 panic（已实测崩两次）；`fcov` 必毒。

**本次另按用户决定"暂不支持"3 条**（实测其实 PASS，但本轮先不测）：

| 命令 | 实测结果 | 处置 |
|---|---|---|
| `cam_set photo single size 3m` | ✅ PASS（`1920x1440`） | **暂不支持**（本轮不列） |
| `cam_set photo heif size 8m` | ✅ PASS | **暂不支持**（本轮不列） |
| `cam_set photo heif size 720p` | ✅ PASS | **暂不支持**（本轮不列） |

> ⚠ **"暂不支持" ≠ 固件不支持**：这 3 条固件实测能拍成功，只是本轮 `photo_only` 暂不纳入；勿据此判固件缺陷。

## 3. 精确改动

**目标文件**：`ATS/config/scenarios/photo_only.yaml`（当前为**未提交新文件**）。

**唯一改动**：`tasks[0].override.photo_modes` 列表 → 下列 **12 条**（mode-major：auto→single→mfnr→hdr→heif；mode 内按 size 序 `12m,1080p,480p` 等）。

```yaml
        photo_modes:
          # auto（仅 12m 可用）
          - {mode: auto,   size: 12m}
          # single（保留 12m/1080p/720p/480p；3m 暂不支持，8m/w8m 打不开相机，均不列）
          - {mode: single, size: 12m}
          - {mode: single, size: 1080p}
          - {mode: single, size: 720p}
          - {mode: single, size: 480p}
          # mfnr（仅 12m 可用）
          - {mode: mfnr,   size: 12m}
          # hdr（仅 12m 可用）
          - {mode: hdr,    size: 12m}
          # heif（保留 12m/w8m/3m/1080p/480p；8m、720p 暂不支持，不列）
          - {mode: heif,   size: 12m}
          - {mode: heif,   size: w8m}
          - {mode: heif,   size: 3m}
          - {mode: heif,   size: 1080p}
          - {mode: heif,   size: 480p}
```

> 12 条明细：`auto-12m`；`single-{12m,1080p,720p,480p}`；`mfnr-12m`；`hdr-12m`；`heif-{12m,w8m,3m,1080p,480p}`。

**同步更新文件头注释**（当前写「共 42 条」「6×7」等）：
- `# 用途：...对 mode × size 做**全枚举（6 × 7 = 42 条）**，单轮跑完即止（ADR-018）。`
  → 改为说明**已按 2026-11-20 实测收缩为 12 条**，并指向 test_report。
- 顶部「顺序 mode-major ... 共 42 条」注释同步改为「共 12 条」。

### 3.2 改为循环 20 轮（本次一并改）

**目标**：`scenario.loop` 由「单轮」改为**整轮循环 20 次**（每轮完整遍历上面 12 条 photo_modes）。

当前（`photo_only.yaml` L16-17）：

```yaml
  loop:
    enable: false          # 单轮跑完即止（不做整轮循环）
```

改为（与 `stress.yaml` / `recovery_validation.yaml` 的 loop 写法一致）：

```yaml
  loop:
    enable: true
    count: 20
```

- 语义：Runner 每轮执行一次 tasks（photo 模块遍历 12 条组合），共 20 轮 = **12 × 20 = 240 次拍照**。
- 注释可保留说明「20 轮 × 12 组合 = 240 次拍照」。

**不改**：scenario 骨架其余项（name / preview / prepare / cleanup）、`- module: photo` / `override.ftp_download: false` 全部不动。

## 4. 验收标准

### 离线

1. `ATS/config/scenarios/photo_only.yaml` 的 `photo_modes` 元素数 = **12**；
2. 列表内**不含**：`{mode: fcov, ...}`、`{mode: <auto|single|mfnr|hdr>, size: <8m|w8m>}`、`{mode: single, size: 3m}`、`{mode: heif, size: <8m|720p>}`；
3. `scenario.loop` = `enable: true` + `count: 20`；
4. `python3 -m ATS.main --scenario photo_only --dry-run` exit 0。

### 真机（可选，若跑）

12 条 `cam_set photo <mode> size <size>` + `cam_run photo` 全回 `Capture completed successfully.`（12/12 PASS），不再出现 `does not support` / `cam open failed` / 板子卡死；20 轮连续跑板子不死机。

## 5. 明确不做

- ❌ 不改 `photo_only.yaml` 的 name/preview/prepare/cleanup（loop 仅按 §3.2 改成 20 轮）。
- ❌ 不改 `photo_only` 之外的任何场景（`stress` / `recovery_validation` / 等属 ADR-018 任务单范围，另案）。
- ❌ 不改 `ATS/drivers/photo_commands.py`、`ATS/modules/photo.py`（这些属 ADR-018 任务单 `code_task_photo_size关键字显式化.md` 范围）。
- ❌ 不修改 `docs/`（Document Agent 负责）。

## 6. 交付要求

1. 若本改动会随分支提交，按工程红线 1 在 `docs/03_development/devlog/` 新建记录并更新索引（纯配置改动；若认为无需 devlog，在提交信息中说明即可）；
2. 真机若发现 12 条中有未预期的 FAIL，**先回报**，不要自行改判据。

## 7. 备注（Document Agent 已完成的同步）

- 实测结论已沉淀：[test_report_20261120](../../04_testing/test_report_20261120_photo_mode_size全枚举.md)、`known_issue.md`（固件 bug 表 + 脚本侧表）、`ADR-018` Open、`next_step.md`。
- 本任务单只解决「`photo_only.yaml` 用哪些命令」；ADR-018 的 `photo_matrix.yaml` / 各场景结构体迁移仍按 `code_task_photo_size关键字显式化.md` 独立推进。
- **待用户拍板（不阻塞本任务单）**：`8m/w8m` 是否永久跳过、`fcov` 是否单列独立场景、"暂不支持"的 3 条何时恢复 —— 见 test_report §七 TODO-CONFIRM。
