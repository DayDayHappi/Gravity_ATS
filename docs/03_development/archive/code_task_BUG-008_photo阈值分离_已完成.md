# Code Agent 任务单：BUG-008 photo 缩略图/HEIC 大小阈值分离

> 由 Document Agent 出具，交 Code Agent 执行。
> **状态：✅ 已完成**（2026-11-05，devlog `20261105_1116`，真机验证通过）。
> 依据：[BUG-008](../bugfix/BUG-008-photo缩略图套用主图大小阈值致误判FAIL.md)（根因与证据）。
> 文档预授权：本任务属 Level 1（模块内部实现）+ 新增可选配置键（Level 2），**Document Agent 已完成复核**，
> Code Agent 无需再发 `Document Agent Request`；实施后按本文「交付要求」写 devlog 即可。

## 1. 目标

消除 photo 辅助校验对**固件缩略图 `*_thum.jpg`** 与 **HEIC** 套用主图 10KB 阈值的假 FAIL，
同时保住「已下载必校验」「未列出图片是固件假成功信号」两条判据红线。

## 2. 现状事实（真机实测，勿再重复论证）

最近一次 stress：`logs/stress/20261104/20261104_182626`（运行中，观测至 cycle 48）

| 类别 | 数量 | 大小范围 | <10KB 数 | 说明 |
|---|---|---|---|---|
| 主图 `Image_<ts>_<n>.jpg` | 2544 | 11776 – 2186240 B | 0 | 正常 |
| 缩略图 `Image_<ts>_thum.jpg` | 384 | 9046 – 16292 B | **240** | 480×360，全部可解码、以 `FF D9` 结尾，文件完整 |
| HEIC（heif 模式） | 48 | 10858 – 11826 B | 0（本 run） | 另一 run `20261103_132557`：69 个中 39 个 <10KB，最小 6855B（固件日志 `heic saved (1920x1440, 6855 bytes)`） |

- 该 run 共 240 条 photo FAIL，**全部**为 `..._thum.jpg 校验失败`，无一条来自主图。
- 失败模式集中在亮场景：`auto` / `hdr 2` / `mfnr` / `single` / `single 12m`（缩略图 9.0–9.3KB）；
  `hdr 0` / `hdr 1` / `hdr 3` 因缩略图约 16KB 侥幸不触发。**同一逻辑缺陷，表现随场景亮度漂移**。
- `single 480p` 主图仅 11776B，距 10KB 只有 1.7KB 余量，需在实现中保留该档位可过。

## 3. 缺陷位置（精确锚点）

`ATS/modules/photo.py`

| 位置 | 现状 | 问题 |
|---|---|---|
| L180-190 `_list_jpgs()` | 按 `.jpg/.heic/.heif` 列目录 | 把 `*_thum.jpg` 与主图混为一类，无产物类型信息 |
| L143-153 下载/校验循环 | 逐张 `download()` → `_verify_jpeg(local, min_kb)` | 传入单一 `min_kb` |
| L202-216 `_verify_jpeg()` | 先统一 `size < min_kb*1024` 判 FAIL，再按扩展名做 JPEG/HEIF 头校验 | 缩略图/HEIC 共用主图阈值 |
| L49 | `min_kb = int(self.config.get("photo_min_size_kb", 10))` | 单一阈值来源 |
| `ATS/config/modules/photo.yaml` | `photo_min_size_kb: 10` | 无分档配置 |

## 4. 实现方案（推荐 A；B 为备选，二选一，不要混做）

### 方案 A（推荐）：按产物类型分档阈值

1. 新增**产物分类**（模块内部私有函数即可）：按文件名后缀判定
   - `*_thum.jpg` → `thumbnail`
   - `.heic` / `.heif` → `heif`
   - 其余 `.jpg` → `main`
2. `ATS/config/modules/photo.yaml` 新增两个可选键（缺省值即下方值，老场景不配也安全）：
   ```yaml
   photo_min_size_kb: 10          # 主图（维持现值，勿改）
   photo_thumb_min_size_kb: 4     # 缩略图 480×360，实测 8.4–22.5KB
   photo_heif_min_size_kb: 4      # HEIC，实测 6.9–83KB
   ```
3. `_verify_jpeg(local, min_kb)` 改为按类别取阈值（建议签名 `_verify_image(local, kind, min_kb_by_kind)`
   或直接传分类后的 `min_kb`；保持函数内「阈值 → 格式头」顺序）。
4. FAIL 文案保留分类信息，便于事后 grep：例如 `文件过小 9135B < 4KB（缩略图）`；
   **PASS/FAIL 判定语义不变**（已下载且校验失败 → FAIL）。

### 方案 B（备选）：缩略图只留证不参与校验

- 仍下载 `*_thum.jpg`（保留现场证据），但校验集合只含主图与 HEIC；
- HEIC 仍需独立阈值（否则 heif 模式继续误判）；
- 适用于「确认缩略图不是交付产物」的前提。该前提当前**未确认**（见 §8），故不作首选。

### 禁止做法

- ❌ 直接把 `photo_min_size_kb` 从 10 调到 8 —— 会把主图阈值一起放宽，`single 480p` 等低分辨率主图的
  损坏文件将漏检，等于削弱判据。
- ❌ 把「下载成功但校验失败」降级为 PASS。
- ❌ 对 `*_thum.jpg` 只跳过大小检查但保留文件头检查的做法**可以**，但不得跳过格式头校验。

## 5. 验收标准

### 离线（必须全绿）

在 `tests/` 新增或扩展 photo 单测（参考 `tests/test_photo_heif.py` 的 `_FakeFtp` + `_write` 写法）：

1. 480×360 缩略图 9KB（真实样本尺寸）→ 按缩略图档位判定 **通过**；
2. 主图 12KB → 按主图 10KB 档位通过；主图 9KB → **FAIL**（证明未放宽主图阈值）；
3. HEIC 7KB 且 `ftyp` 头合法 → **通过**；8KB 但无 `ftyp` → **FAIL**（头校验仍在）；
4. `*_thum.jpg` 截断到 3KB → **FAIL**（缩略图档位仍生效）；
5. 老配置（yaml 不写新增两键）→ 使用缺省值，行为与用例 1~4 一致；
6. 全量回归：`python3 -m unittest discover -s tests` 全过（当前基线 57+ 个用例）。

### 真机（必须回填结果）

1. `python3 -m ATS.main --scenario stress --no-interactive-wifi` 连续 ≥2 个 cycle；
2. 断言：run.log 中 `_thum.jpg 校验失败` 计数为 **0**；`photo[auto|hdr 2|mfnr|single|single 12m]` 全 PASS；
   `heif` 模式 PASS；
3. 反向验证：手工把一个已下载主图截断到 5KB 后跑 `_verify_jpeg` 直接调用（或临时改本地副本），
   确认仍判 FAIL —— 证明判据没有变成「有下载就 PASS」；
4. 把「缩略图/HEIC/主图」的最小与最大实测字节数记入 devlog，作为后续阈值调整依据。

## 6. 交付要求（Code Agent 的文档义务）

只允许改：`ATS/modules/photo.py`、`ATS/config/modules/photo.yaml`、`tests/test_photo_*.py`、
`docs/03_development/devlog/`。

必须：

1. 新建 `docs/03_development/devlog/<YYYYMMDD>_<HHMM>_photo缩略图与HEIC阈值分离.md`，
   含 Change / Files / Reason / Verification（离线 + 真机证据） / Known limitation；
2. 在 `docs/03_development/devlog/README.md` 索引追加一行；
3. 在 devlog 里**明确列出新增的配置键名与缺省值**（Document Agent 据此同步
   `01_architecture/module_design.md` 的 photo Input 段）。

禁止改：`docs/01_architecture/`、`docs/02_design/`、`docs/05_handoff/`（本任务单与 BUG-008 已由
Document Agent 维护，Code Agent 完成后回报状态即可）。

## 7. 与其它待办的关系

- 与本任务无耦合、不要顺手改：BUG-007（健康监测 FTP 盲区）、ADR-017 上传证书、utest 超时。
- 若实施中触发 `ATS/modules/photo.py` 的其他历史缺陷（例如 `_list_jpgs` 漏列非 jpg 产物），
  **只记录到 devlog + 回报**，不在本任务内扩大改动范围。

## 8. 遗留待确认（不影响本任务实施）

- **TODO-CONFIRM（需求侧）**：`*_thum.jpg` 是否属产品交付产物？若固件后续移除缩略图，
  方案 A 的缩略图档位将成为死配置，届时清理。当前按「固件有产出就校验」处理。
- **TODO-CONFIRM（阈值稳定性）**：缩略图尺寸随画面亮度在 8.4–22.5KB 间漂移，`4KB` 为安全下界；
  若后续出现更暗/更简单的场景仍有风险，需增加「按 480×360 尺寸 + 格式头」的第二重判据（不在本任务内）。
