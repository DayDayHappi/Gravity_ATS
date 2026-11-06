# BUG-008：photo 把固件缩略图 `*_thum.jpg` 一并套用主图大小阈值，致误判 FAIL

## Problem

stress 压测（`logs/stress/20261104/20261104_182626`，2026-11-04 18:26 启动，观测至 2026-11-05 10:59 cycle 48）
累计 **240 条 photo FAIL**，全部形如：

```
[FAIL] photo[hdr 2] - 文件过小 9135B < 10KB | 拍照成功，保存到 /emmc/PIC/20260101_000100_0095 | Image_20260101_000100_0095_thum.jpg 校验失败
```

失败文件名**全部是固件生成的缩略图 `*_thum.jpg`**（240/240），主要集中 5 个模式
（`auto` / `hdr 2` / `mfnr` / `single` / `single 12m`），另有 `hdr 0/1/3` 偶发
（12:25 与 12:45 出现 5 次，缩略图 9026–9844B）——即**同一缺陷随画面亮度漂移**，不是某几个模式特有。

> 该 run 最终跑完 56 cycle：photo PASS 395 / FAIL 277，`_thum.jpg 校验失败` 277 条、`文件过小` 277 条，两者完全相等。

## Root Cause

`ATS/modules/photo.py` 的辅助校验链：

1. `_list_jpgs()`（L180-188）按扩展名 `(".jpg", ".heic", ".heif")` 列目录 → **把固件缩略图 `*_thum.jpg` 也算作待校验图片**。
2. 下载循环（L144-155）逐张下载并 `_verify_jpeg(local, min_kb)`。
3. `_verify_jpeg()`（L202-205）对**所有**文件统一做 `size < min_kb*1024`（`photo_min_size_kb: 10`）判断。

固件缩略图是 **480×360** 的小图，实测 8.4–22.5KB，随场景亮度/复杂度波动：
亮场景（mean≈132）约 **9.0–9.3KB**，暗场景（mean≈42）约 16KB。亮场景缩略图跌破 10KB → 判「文件过小」。

判据语义「已下载的图片必逐张校验，任一失败判 FAIL」（devlog `20260928_1106`）本身正确，
问题在于**未按产物类型区分阈值**：主图（1008×4032 / 1920×1080 等）12KB–2.1MB，
缩略图（480×360）本身就只有约 9KB，二者不可能共用 10KB 阈值。

## 证据（同一 run，跑完 56 cycle 后统计）

| 类别 | 文件数 | 最小值 | 10KB 以下 | 结论 |
|------|--------|--------|-----------|------|
| 主图 `*_<n>.jpg` | 2966 | 11264B（`single 480p`） | **0** | 主图全部达标 |
| 缩略图 `*_thum.jpg` | 448 | 9026B | **277** | 失败全部来自这里 |
| HEIC | 56 | 10858B | 0（本 run） | 见下「同类风险」 |

- 固件日志同步确认缩略图尺寸：`I/App Dfs: thumbnail saved 9135 bytes`，与本地文件字节数一致。
- 448 张缩略图全部可正常解码（Pillow：`480×360`）且以 `FF D9` 结尾，**文件本身完整、非截断、非损坏**。
- 主判据 `Capture completed successfully.` 均正常出现，产品功能是好的。

## 定性

**脚本侧判据缺陷（假 FAIL），非固件 bug、非文件损坏。**
与 known_issue 中「eMMC 假成功」不同：后者表现为「未列出 jpg」，本 bug 表现为「缩略图尺寸低于主图阈值」。

## 修复结果（2026-11-05，devlog `20261105_1116`）

Code Agent 按方案 A 实施，Document Agent 复核结论：**通过**。

**代码**（`ATS/modules/photo.py`）
- 新增 `_classify_image(name)`：`*_thum.jpg` → `thumbnail` / `.heic|.heif` → `heif` / 其余 → `main`。
- 新增 `_min_kb_by_kind(config)`：分档阈值表，缺省 `{main:10, thumbnail:4, heif:4}`。
- `_verify_jpeg(local, min_kb)` → `_verify_image(local, kind, min_kb_by_kind)`：
  保持「先大小、后格式头」顺序，格式分支改由 `kind` 决定，文案带分类（`文件过小 9135B < 4KB（缩略图）`）。
- 下载范围、FAIL/PASS 语义、「已下载必校验」「未列出图片是假成功信号」两条红线均未改。

**配置**（`ATS/config/modules/photo.yaml`）

| 键 | 值 | 适用 |
|---|---|---|
| `photo_min_size_kb` | 10（未改） | 主图 |
| `photo_thumb_min_size_kb` | 4（新增） | 缩略图 |
| `photo_heif_min_size_kb` | 4（新增） | HEIC |

**离线验证（Document Agent 独立复跑）**
- `python3 -m unittest discover -s tests` → **71 tests OK**（HEAD 基线 59，+12）。
- 用真实产物回放新逻辑（全部历史 `logs/**/photos/`）：main 21594 张 / thumbnail 1676 张 / heif 299 张，**fail=0**。
- 反向验证（判据未被削弱）：主图 5120B → `文件过小 … < 10KB（主图）`；缩略图 3072B → `文件过小 … < 4KB（缩略图）`；HEIC 8192B 无 ftyp → `HEIF 头校验失败`。
- `--dry-run` 退出码 0。

**真机验证（已回填）**：`logs/stress/20261105/20261105_133805`（2026-11-05 13:38 启动，加载修复后代码）

| 指标 | 结果 |
|---|---|
| photo PASS / FAIL | **636 / 60** |
| `_thum.jpg 校验失败` | **0**（修复前同口径 277） |
| `文件过小` | **0** |
| 缩略图 <10KB 的目录数 | 265 个，全部 PASS（最小 9071B） |
| 覆盖模式 | 12 个模式（含 `heif`、`single 480p/720p/1080p/12m`）循环 58 轮 |

证据样本：`photos/hdr_2_20260101_063411_2265/…_thum.jpg` = 9071B（<10KB），run.log L7888 `[PASS] photo[hdr 2] - 全部 10 张图片校验通过`。

> 该 run 的 60 条 photo FAIL **与阈值无关**：全部是 `拍照未完成保存`，起于 cycle 54，
> 串口同步打印 `E/App Dfs: eMMC full: not enough free space (0KB free, need 3072KB), photo not started`。
> 属另一问题（压测把 eMMC 写满）。**该问题属范围外，脚本不处理**（用户 2026-11-06 决策），见 known_issue。

## 同类风险（修复时一并覆盖）

1. **HEIC 天然接近阈值**：`heif` 产物 6.9–83KB（`20261103_132557` run：69 个 heic 中 39 个 <10KB，
   固件日志 `heic saved (1920x1440, 6855 bytes)`）→ 已由 `photo_heif_min_size_kb: 4` 覆盖。
2. **低分辨率主图余量极小**：`single 480p` 主图 10240–12288B，**最小样本距 10KB 阈值为 0**；
   实测 413 张 480p 主图中 34 张 ≤11264B。当前未调主图阈值（下调会削弱损坏检测），
   属**未关闭风险**，见文末 TODO-CONFIRM。
3. 缩略图尺寸场景相关（8.4–22.5KB），**不存在**一个能跨场景稳定的固定字节阈值 → 4KB 为安全下界。

## 修复方案（已实施：方案 A）

1. **按产物类型分阈值**（采用）：`_classify_image()` + `_min_kb_by_kind()`，
   主图沿用 `photo_min_size_kb`，缩略图/HEIC 用新增键。
2. ~~缩略图不参与「必校验」集合~~（未采用：缩略图是否交付产物未确认，保留校验更安全）。
3. ~~取消字节数阈值改尺寸校验~~（未采用：避免引入 Pillow 运行依赖；留作长期方向）。

红线保持：**不得放宽到「有下载就 PASS」**——`test_strategy.md` 的「已下载必校验」与
「未列出图片是假成功信号」两条同时生效。

## Verification（已回填，见上文「修复结果」）

- 离线：71 tests OK；真实产物全量回放 fail=0；截断/坏头反例仍 FAIL。
- 真机 `20261105_133805`：`_thum.jpg 校验失败` 与 `文件过小` 均为 **0**，636 次 photo PASS。

## 遗留 TODO-CONFIRM

1. **`single 480p` 主图余量为 0**：实测最小 10240B 恰好等于 10KB 阈值（`20261103_132557`）。
   一旦画面更简单就会假 FAIL。需人工拍板：降低该档阈值 / 单独为低分辨率主图设档 /
   改为「格式头 + SOF 尺寸校验」。**本次未改**（改动需新的判据决策，非本 BUG 范围）。
2. **`*_thum.jpg` 是否属产品交付产物**：若固件后续移除缩略图，`photo_thumb_min_size_kb` 成为死配置。

## 关联

- 代码：`ATS/modules/photo.py`（`_classify_image` / `_min_kb_by_kind` / `_verify_image`）
- 配置：`ATS/config/modules/photo.yaml`（三档阈值）
- 测试：`tests/test_photo_size_thresholds.py`（12 例）、`tests/test_photo_heif.py`（适配新入口）
- devlog：`20261105_1116_photo缩略图与HEIC阈值分离.md`（实施记录）
- 任务单（已完成归档）：`../archive/code_task_BUG-008_photo阈值分离_已完成.md`
- 历史：devlog `20260928_1106`（引入「整目录 + 已下载必校验」）、`20261014_1634`（HEIC 纳入校验）
- 同类记录：`20261103_132557`（192 缩略图 + 39 heic）、`20261104_133623`（25 缩略图 + 3 heic）
