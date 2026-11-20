# photo_only/stress 的 photo 命令替换为实测可用 12 条

## Date
2026-11-20 09:12

## Task
按 Document Agent 两份 Level 1 纯配置任务单实施：
1. `code_task_photo_only收缩为可用命令.md`：`photo_only.yaml` 的 `photo_modes` 收缩为 **12 条**（42→15→12），并把 `loop` 改为 **20 轮**。
2. `code_task_stress_photo替换为可用命令.md`：`stress.yaml` 删除原 photo task（含 num 的 11 条）→ 替换为 **12 条**（每 mode 一个 task、单元素 `photo_modes` + `repeat: 1`）。

**口径（两次收缩）**：42 组合 → 真机实测 15 可拍 → 用户再定 `single 3m`/`heif 8m`/`heif 720p`「暂不支持」（实测 PASS，本轮不纳入）→ **最终 12 条**。

## Changed
### photo_only.yaml
- `tasks[0].override.photo_modes`：**12 条**（mode-major auto→single→mfnr→hdr→heif）：
  `auto-12m`；`single-{12m,1080p,720p,480p}`；`mfnr-12m`；`hdr-12m`；`heif-{12m,w8m,3m,1080p,480p}`。
- `scenario.loop`：`enable: false`（单轮）→ `enable: true` + `count: 20`（20 轮 × 12 = **240 次拍照**）。
- 头注释同步：`42/15 条` → `12 条`、`20 轮 × 12 = 240 次`，并注明排除项（fcov / 8m·w8m / 3m·1080p·720p·480p 非 single / 暂不支持 3 条）。
- 骨架（name/preview/prepare/cleanup）、`ftp_download: false` 零改动。

### stress.yaml
- 删除原 L17–72 的 photo 段（11 个 task：`hdr 0~3`(num) / `mfnr` / `auto` / `single` / `single 1080p/720p/480p` / `single 12m` / `heif`）及其顶部注释。
- 替换为 **12 个 photo task**（单元素 `photo_modes` + `repeat: 1`），顺序 **hdr → mfnr → auto → single → heif**，`single 12m` 置末位（沿用「末位补 12m 规避下一轮切换失败」实践）：
  `hdr-12m` → `mfnr-12m` → `auto-12m` → `single-1080p` → `single-720p` → `single-480p` → `single-12m` → `heif-12m` → `heif-w8m` → `heif-3m` → `heif-1080p` → `heif-480p`。
- 全部用 `size`、**无 `num`**。
- 其余（video×6 / video_integrity / rtmp / prepare / loop / cleanup）**零改动**。

## Files
- `ATS/config/scenarios/photo_only.yaml`
- `ATS/config/scenarios/stress.yaml`

## Reason
- 2026-11-20 真机逐条实测（`test_report_20261120_photo_mode_size全枚举.md`）：42 组合仅 15 可拍；12 条 SET 被拒、10 条 cam open failed、5 条 fcov 锁死板子。
- `8m/w8m` 小概率整板 panic、`fcov` 必毒 → 排除；用户另定 3 条实测可用项「暂不支持」→ 最终 12 条。
- stress 原配置用 `num`（`{mode: hdr, num: 0~3}`）等旧口径，与新 ADR-018（无 num、size 必填）不符，故整段替换。

## Verification
- **photo_only**：`yaml.safe_load` OK；`photo_modes` 元素数 = **12**；不含 `fcov`、不含 `{auto|single|mfnr|hdr}×{8m|w8m}`、不含 `single-3m`/`heif-8m`/`heif-720p`；每元素含 `mode`+`size`、无 `num`；`loop={enable:true,count:20}`。
- **stress**：`module: photo` task 数 = **12**；photo 序列 = hdr-12m/mfnr-12m/auto-12m/single-{1080p,720p,480p,12m}/heif-{12m,w8m,3m,1080p,480p}；`grep -c "num:"` = **0**；其余 task = video×6 + video_integrity×1 + rtmp×1（与改动前一致）。
- `python -m ATS.main --scenario photo_only --dry-run` → **exit 0**。
- `python -m ATS.main --scenario stress --dry-run` → **exit 0**。
- 未跑真机（按已有实测报告收缩命令集）。

## Known limitation
- 分两轮收缩（15→12）后，`photo_only` 与 `stress` 都变 12 条；二者命令集**一致**（stress 按逐 mode 拆 task，photo_only 单 task 遍历）。
- `single 3m`/`heif 8m`/`heif 720p` 属「暂不支持」（实测可拍、本轮不纳入），非固件缺陷；何时恢复见 test_report §七 TODO-CONFIRM。
- `8m/w8m`（heif 除外）是否永久跳过、`fcov` 是否单列场景——待用户拍板。
- **工作区 `photo_commands.py`/`photo.py` 仍为「含 num」的未提交实现**（`PhotoParams(mode,size=None,num=None)`）；本次两场景配置**均用 `size`、无 `num`**，与 ADR-018 修订版一致；但**该未提交实现本身仍需按 ADR-018 修正（删 num、size 必填）**，属另一任务单 `code_task_photo_size关键字显式化.md` 范围，本次未动源码。
- `loop=20 轮 × 12 = 240 次拍照`，长跑若遇 eMMC 写满（范围外）需人工控制轮次。
