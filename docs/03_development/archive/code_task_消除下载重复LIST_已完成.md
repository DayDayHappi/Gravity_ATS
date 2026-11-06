# Code Agent 任务单：消除 photo/video 下载时每个文件重复 LIST 目录

> 由 Document Agent 出具，交 Code Agent 执行。
> **状态：✅ 已完成**（2026-11-06，devlog `20261106_1129`）。复核结论见耗时报告 §八。
> 依据：[04_testing/test_report_20261105_压测耗时分析.md](../../04_testing/test_report_20261105_压测耗时分析.md)（O1 项）。
> 文档预授权：Level 1（模块内部实现）+ driver 可选参数，**Document Agent 已完成复核**，
> Code Agent 无需再发 `Document Agent Request`；实施后按本文「交付要求」写 devlog 即可。

## 1. 目标

消除 `FtpClient.download()` 内部为取文件大小而**重复 LIST 父目录**的开销——调用方已经 LIST 过同一个目录，
把已知 size 传下去即可。判据语义、下载行为、重试逻辑均不变。

## 2. 现状事实（实测，勿重复论证）

真机 `logs/stress/20261105/20261105_133805`（58 cycle / 19.7h）：

| 事实 | 数据 |
|---|---|
| photo 每目录 connect 数 | 严格等于 **文件数 + 2**：`(1,3)` `(2,4)` `(7,9)` `(9,11)` `(10,12)` |
| photo 单文件循环耗时 | median **1.83s** / mean 2.30s（n=3922） |
| 目录 LIST 单次耗时 | median **0.84s** / mean 2.43s / P90 6.39s（n=1902） |
| video 下载段 | 单文件 avg 14.1s，其中 connect 0.12s |
| **LIST size 准确性** | video 630/630 样本，LIST 报的 KB 与本地实际字节**完全一致**；photo 全程 0 次「下载提前结束」 |
| photo 总下载窗口 | 636 次 × 9.4s ≈ 100 分钟 |

**根因**：`ftp_client.py` L255 `total = self.size(remote_path)`，而 `size()`（L209-221）注释自认
「该FTP不支持SIZE命令，用LIST父目录解析」→ 每取一个文件大小就 `CWD → LIST → CWD` 一次（3 个 RTT）。
10 张图的目录 = 1 次 LIST（列名）+ 10 次 LIST（取 size）= **11 次，其中 10 次纯重复**。

**现成条件**：`FtpClient.list_files_detail()`（L136）已存在且**全工程无调用方**，返回 `[(name, size), ...]`，正是此用途。

## 3. 精确改动锚点

### 改动 1 — `ATS/drivers/ftp_client.py`

**L223-255** `download()` 增加可选参数 `size_hint`：

```python
def download(self, remote_path: str, local_path: str, timeout: float = 30.0,
             retries: int = 5, size_hint: int = None) -> bool:
```

方法体 L255：

```python
# 调用方若已列目录拿到大小（list_files_detail），直接用，省一次 LIST 父目录；
# size_hint 缺失/非法时回退原有 size() 行为，向后兼容。
total = size_hint if (size_hint and size_hint > 0) else self.size(remote_path)
```

- `size_hint=None`（默认）时行为与现状**完全一致** → 现有其它调用方零影响。
- `total` 的后续 4 处用途（L266 已下完判断、L276 完整性、L280 警告文案、L291 最终返回）语义不变，**不要改**。
- docstring 增加 `size_hint` 说明：「调用方已 LIST 得到的文件字节数；None 时内部 size()（会 LIST 父目录）」。

### 改动 2 — `ATS/modules/photo.py`

**L216-229** `_list_jpgs()`：返回值从 `[name, ...]` 改为 `[(name, size), ...]`

```python
def _list_jpgs(self, ftp, dir_path):
    """列指定目录图片，返回 [(name, size), ...]（.jpg / .heic / .heif）。

    size 供 download(size_hint=...) 复用，避免每个文件再 LIST 一次父目录。
    heif 拍照固件产出 .heic（日志 `...heic saved` / `Save Heif Successful`），
    若只认 .jpg 会漏掉 heif 模式产物，导致「未列出 jpg 辅助验证」降级 PASS。

    固件缩略图 `*_thum.jpg` 也在此列出（仍下载留证 + 校验），但其大小阈值
    在 ``_verify_image`` 中按产物类型单独取（BUG-008）。
    """
    try:
        return [(n, sz) for n, sz in ftp.list_files_detail(dir_path)
                if n.lower().endswith((".jpg", ".heic", ".heif"))]
    except Exception:
        return []
```

**L179-183** 下载循环解包（`for jpg in jpgs` 在 L179，`download()` 在 L183）：

```python
for jpg, size in jpgs:
    ...
    if not ftp2.download(remote, local, timeout=30, retries=2, size_hint=size):
```

L199/L204 的 `len(jpgs)` 无需改（列表长度不受影响）。

### 改动 3 — `ATS/modules/video.py`

video 有同类浪费但形态不同：L152 已 `sz = ftp2.size(video_path)` 拿到大小，L169 `download()` 内部**又** `size()` 一次。

**L169**：

```python
if ftp2.download(video_path, local, timeout=20, retries=6, size_hint=sz):
```

L152/155 的 `size()` 保留（首次取大小 + 失败重试），只是不再重复第二次。

### 改动 4 — 测试适配（**必改，否则测试红**）

`tests/test_photo_heif.py`：
- `_FakeFtp`（L25-30）当前只实现 `list_files()` → 补 `list_files_detail()`，返回 `[(name, size), ...]`。
- `test_list_jpgs_includes_heic_heif`（L59-62）断言 `["a.jpg", "b.HEIC", "c.heif"]` → 改为带 size 的元组列表。

`tests/test_photo_size_thresholds.py`：**不涉及** `_list_jpgs`，无需改。

**新增用例**（建议放 `tests/test_ftp_download_size_hint.py`）：
1. `size_hint=12345` → `download()` **不调用** `size()`（用 mock 计数断言）。
2. `size_hint=None` → 仍调用 `size()`（向后兼容）。
3. `size_hint=0` / 负数 → 回退到 `size()`。
4. `_list_jpgs` 返回 `[(name, size), ...]`，且过滤仍只含 `.jpg/.heic/.heif`。

## 4. 验收标准

### 离线（必须全绿）

1. `python3 -m unittest discover -s tests` 全过（当前基线 **71**，改后应 ≥ 71，新增用例计入）。
2. `python3 -m ATS.main --scenario stress --dry-run` 退出码 0。
3. 上述新增 4 条用例全过。

### 真机（必须回填结果）

跑 `python3 -m ATS.main --scenario stress --no-interactive-wifi` **2~3 cycle** 即可（不需跑满）。

**主验收指标（最直观）**：`run.log` 中每个 photo 模块的 `FTP 已连接`（排除紧随 `FTP 已重新连接` 的那行）次数。

> ⚠️ **任务单原期望「connect 次数恒为 2」有误（2026-11-06 更正）**：`download()` 每次都要
> `connect()`（板端 FTP 3s 空闲断会话，BUG-003 红线），N 个文件必然 N 次 connect，与本次优化无关。
> 本次收益是**单文件内部少一次 LIST**，不是减少 connect。正确的可观测指标见下表「真实 LIST 次数」。

**正确的验收指标（真实 LIST 次数，需临时插桩计数 `FtpClient._list_entries()`）**：

| 项 | 改前 | 改后期望 |
|---|---|---|
| photo 一个 10 图目录 | **11** 次 | **1** 次 |
| photo 一个 1 图目录 | 2 次 | 1 次 |
| video 一次下载 | 2 次 | 1 次 |
| `size()` 调用次数（10 图目录） | 10 次 | **0 次** |

**次验收指标**：单文件下载间隔（相邻两次 `FTP 已连接`）中位 **1.83s → ~0.74s**。

**功能回归（必须确认未破坏）**：
- photo 各模式仍 PASS，`全部 N 张图片校验通过` 张数与改前一致。
- 人为把本地一个已下载文件截断后重跑单测，确认续传逻辑仍工作（`total` 判断未被破坏）。
- 断网/停 FTP 场景下 `size_hint` 路径不抛异常（`download` 仍返回 False 而非崩溃）。

## 5. 交付要求

只允许改：`ATS/drivers/ftp_client.py`、`ATS/modules/photo.py`、`ATS/modules/video.py`、
`tests/test_photo_heif.py`、`tests/test_ftp_download_size_hint.py`（新建）、`docs/03_development/devlog/`。

必须：

1. 新建 `docs/03_development/devlog/<YYYYMMDD>_<HHMM>_消除下载重复LIST.md`，含
   Change / Files / Reason / Verification（离线用例 + 真机 connect 次数前后对比数字） / Known limitation；
2. 在 `docs/03_development/devlog/README.md` 索引追加一行；
3. 在 devlog 中**明确回填真机实测**：`(文件数, connect数)` 的改前/改后分布表、单文件循环耗时中位数。

禁止改：`docs/01_architecture/`、`docs/02_design/`、`docs/04_testing/`、`docs/05_handoff/`
（本任务单与耗时报告已由 Document Agent 维护，Code Agent 完成后回报状态即可）。

## 6. 明确不要做的

- ❌ **不要**在 `FtpClient` 里加 `_size_cache` 之类的隐式缓存。理由：隐藏状态、新拍照后目录变化易脏读、
  `connect()` 清缓存时机难界定。显式 `size_hint` 参数职责清晰，出问题一眼可见。
- ❌ **不要**改 `download()` 的续传/REST/重试逻辑（与本次无关，BUG-003 已验证）。
- ❌ **不要**顺手改 `photo.py` 的死参数（`ftp` 形参、`cap_timeout`、`_list_pic_dirs`/`_wait_new_dir`）——
  那是耗时报告里的 O5 项，建议**单独一次提交**，避免与本次性能改动混在一起难以 review。
- ❌ **不要**动 eMMC 容量/清理（用户已决策范围外）。

## 7. 风险与防护（已评估）

| 风险 | 评估 | 防护 |
|---|---|---|
| LIST 报的 size 不准 | **已验证无风险**：video 630/630 一致；photo 0 次「下载提前结束」 | 加保底：若实际下载后 `local_sz < total` 且本次用了 hint，先 `self.size()` 复核一次再判续传 |
| 文件仍在写入时 LIST 到半成品大小 | 低 | photo 在 `Capture completed successfully.` 后才 LIST；video 在 `Video recording completed successfully.` 后才取 size，均为完成态 |
| 破坏现有测试 | 已知 | `_FakeFtp` 需同步适配（见改动 4） |
| 其它模块受影响 | 无 | 全工程 `download()` 仅 photo/video 两个调用方；`size_hint` 默认 None 保证向后兼容 |

> 保底复核为**可选增强**：若 Code Agent 认为增加分支复杂度不值得，可省略，但需在 devlog 的
> Known limitation 中说明「依赖 LIST size 准确性，已用 4552 样本验证」。

## 8. 遗留 TODO-CONFIRM

- **缩略图是否仍需下载校验**（耗时报告 O2）：本次不动，缩略图仍下载但省掉重复 LIST 后每张约 0.7s。
  若后续确认缩略图非交付产物，可再省约 19 分钟/run。
