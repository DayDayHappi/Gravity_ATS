# 需求文档：video 录像前恢复 cam_set 发送

> 提出方：Document Agent（根据用户口述「之前临时取消 cam_set，现在恢复」整理，交由 Code Agent 实施）
> 状态：已实施（2026-09-07，devlog `20260907_1652_video录像前恢复cam_set.md`）
> 关联：`docs/03_development/devlog/20260827_0739_video录像前暂时取消cam_set.md`（原始临时禁用，commit a36abc4）
> 关联：`docs/03_development/devlog/20260828_1500_video加FTP下载开关仅录像不下载.md`（新增 `_run_no_ftp` 时沿用了同一临时禁用约定）

## 1. 背景

2026-08-27 起，`ATS/modules/video.py` 录像前临时禁用了 `cam_set video <resolution>` 调用（用户当时口述要求），用 `if False:` 包住原调用段、并加 `TODO-TEMP-DISABLE-CAM_SET` 标记注释，改为直接 `dfs_video_start`。

现用户口述要求**恢复**：录像前重新发送 `cam_set video <resolution>`。本需求即还原该临时禁用，恢复「切分辨率 → 录像」的完整流程。

## 2. 现场定位（Document Agent 已核对源码，Code Agent 按此执行即可）

当前 `ATS/modules/video.py` 中有 **两处** `TODO-TEMP-DISABLE-CAM_SET` 跳过逻辑需要还原：

### 位置 ①：`run()`（FTP 下载模式），约第 69–76 行

```python
        # 2. 设置分辨率
        # TODO-TEMP-DISABLE-CAM_SET: 录像前暂不切分辨率，直接 dfs_video_start；后续恢复 cam_set video。
        #   临时禁用（用户口述）：跳过 cam_set，直接进入 dfs_video_start。恢复时删掉下面这段跳过逻辑、
        #   还原 cam_set 调用即可。resolution 变量保留（logger.step / logger.info 仍在使用）。
        if False:
            r = console.exec_sync(f"cam_set video {resolution}", timeout=10.0)
            if not r.success:
                return self._mk("FAIL", f"设置分辨率 {resolution} 失败", r.clean, timer)
```

### 位置 ②：`_run_no_ftp()`（纯录像模式，video_ftp_download=false），约第 167–172 行

```python
        # TODO-TEMP-DISABLE-CAM_SET: 录像前暂不切分辨率，直接 dfs_video_start（与 FTP 模式
        #   同一临时禁用约定）。恢复时删掉这段跳过逻辑、还原 cam_set 调用即可。
        if False:
            r = console.exec_sync(f"cam_set video {resolution}", timeout=10.0)
            if not r.success:
                return self._mk("FAIL", f"设置分辨率 {resolution} 失败", r.clean, timer)
```

## 3. 修复要求

### 3.1 位置 ① `run()` 还原为

删除 `TODO-TEMP-DISABLE-CAM_SET` 三行注释与 `if False:` 包裹层，把 `cam_set` 段缩进还原为顶格（与模块内其它同步命令一致）：

```python
        # 2. 设置分辨率
        r = console.exec_sync(f"cam_set video {resolution}", timeout=10.0)
        if not r.success:
            return self._mk("FAIL", f"设置分辨率 {resolution} 失败", r.clean, timer)
```

### 3.2 位置 ② `_run_no_ftp()` 还原为

删除 `TODO-TEMP-DISABLE-CAM_SET` 两行注释与 `if False:` 包裹层，还原为：

```python
        r = console.exec_sync(f"cam_set video {resolution}", timeout=10.0)
        if not r.success:
            return self._mk("FAIL", f"设置分辨率 {resolution} 失败", r.clean, timer)
```

### 3.3 补充一致性修正（模块 docstring）

模块头 docstring 第 19–21 行「流程（纯录像模式，video_ftp_download=false）」当前只列了 `dfs_video_start`，未列 `cam_set`。恢复后纯录像模式同样会先切分辨率，docstring 应同步为：

```text
流程（纯录像模式，video_ftp_download=false）：
1. ``cam_set video 1080p``
2. ``dfs_video_start`` -> sleep(录像时长) -> ``dfs_video_stop``
3. 等到 ``Video recording completed successfully.`` 即 PASS
```

（FTP 模式 docstring 第 12–16 行已含 `cam_set video 1080p`，无需改动。）

### 3.4 变量确认（Document Agent 已核对）

- 两处 `r` 变量恢复后均会在其后被 `console.exec_async(...)` 重新赋值，无未使用/命名冲突。
- `resolution` 变量两处恢复后仍被 `logger.step` / `logger.info` 使用，无需删除。

## 4. 验收标准

1. 全仓 `grep -rn "TODO-TEMP-DISABLE-CAM_SET\|if False:" ATS/modules/video.py` 结果为 **空**（该临时禁用标记彻底移除）。
2. `grep -n "cam_set video" ATS/modules/video.py` 命中 **两处** 实际调用（`run()` 与 `_run_no_ftp()`，非注释）。
3. `python3 -m py_compile ATS/modules/video.py` 通过。
4. `python3 -m ATS.main --list-modules` 仍能识别 `video` 模块（无 import 破坏）。
5. 真机（可选，若环境就绪）：`--scenario video_loop`（FTP 模式）与任一 `video_ftp_download=false` 场景各跑一轮，录像前串口可见 `cam_set video 1080p` 发送、随后 `Record Start|f_index=` 触发、`Video recording completed successfully.` 判 PASS。

## 5. 边界确认

- **不新增 ADR**：属临时禁用标记的还原，模块内部实现细节，Code Agent 分级 Level 1，只需 devlog 留痕，不动 `01_architecture/` / `02_design/`。
- **改代码必留痕**（工程红线 1）：改动后新建 `docs/03_development/devlog/<YYYYMMDD>_<HHMM>_<描述>.md` 并更新其 README 索引（按时间倒序插到表头）。
- **只改 `ATS/modules/video.py`**，不碰 `photo.py`（拍照的 `cam_set photo <mode>` 从未被禁用，无需处理）。
- **handoff 由 Document Agent 负责**：Code Agent 不要改 `docs/05_handoff/`。恢复完成后，`next_step.md` / `current_status.md` 中「录像前暂时取消 cam_set / 待恢复」相关条目将由 Document Agent 后续清理（本次需求交付后触发 Document Agent 复核）。
