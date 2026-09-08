# video_integrity 新增 all_unchecked selection（全检 + 去重）

## 日期
2026-09-08

## 变更来源
Code Agent Request（纯增量，不改现有枚举行为）：video task 用 repeat 录多个视频时，video_integrity 需「每个视频都检测」且「跨 loop 不重复检」。现有 latest_unchecked（只取最新 1 个，repeat N 漏 N-1）与 all（取全部但不过滤已检，跨 loop 重复检）都无法覆盖，故新增 `all_unchecked`（与 latest_unchecked 对称）。

## 做了什么
纯增量新增 selection 值 `all_unchecked`（= 过滤已检 + 取全部），现有 latest / all / latest_unchecked 行为一字不变：

| 位置 | 改动 |
|------|------|
| `_select_files` 去重过滤 | `if selection == "latest_unchecked"` → `if selection in ("latest_unchecked", "all_unchecked")`（latest/all 仍不去重） |
| `_select_files` 取文件 | 逻辑不变，仅注释补全：`# all / all_unchecked：取全部（all_unchecked 已在上方过滤去重）` |
| `_record_checked` | `!= "latest_unchecked"` → `not in ("latest_unchecked", "all_unchecked")`（all_unchecked 必须写 manifest，否则跨 loop 重复检） |
| yaml selection 注释 | `# all \| latest \| latest_unchecked \| explicit` → 加入 `all_unchecked` |
| 模块 docstring L6 | 「manifest 去重（latest_unchecked）」→「（latest_unchecked / all_unchecked）」，纯注释保持准确 |

## 不改的东西
- latest / all / latest_unchecked 三个现有值行为不变。
- ATS/core/、runner.py、base.py、video.py 全不碰。
- 不引入新默认值：selection 默认仍是 latest_unchecked，yaml 默认值不动。
- 不改场景（用法示例仅文档记录）。

## 改了哪些文件
- `ATS/modules/video_integrity.py`（_select_files 两处、_record_checked、docstring）
- `ATS/config/modules/video_integrity.yaml`（L12 selection 注释）

## 验证结果
1. `python3 -m py_compile ATS/modules/video_integrity.py` → PASS。
2. 逻辑单测（临时脚本直调 `_select_files` + `_record_checked`，3 个文件）：
   - all → 3 个（不去重）✓
   - latest → 最新 1 个 ✓
   - latest_unchecked 首次 → 最新 1 个 ✓
   - all_unchecked 首次 → 3 个 ✓
   - 记录 manifest 后：all_unchecked 再调 → 0 个（去重生效）✓；latest_unchecked 再调 → 0 个 ✓；latest 再调 → 最新 1 个（不去重）✓；all 再调 → 3 个（不去重）✓
3. `python3 -m ATS.main --list-modules / --list-scenarios` → video_integrity 正常识别、stress_traverse_photo_mode / video_integrity 场景列出，无 import 破坏 ✓

## 用法示例（供场景侧后续使用，本次未改场景）
```yaml
- module: video
  repeat: 2
  duration: 180
  override: { video_resolution: "1080p" }
- module: video_integrity
  override:
    input:
      source: "current_run"
      selection: "all_unchecked"     # 全检这 2 个 + 去重
      empty_input_policy: "skip"
```

## 文档影响（报告给 Document Agent，Code Agent 不改）
- next_step.md P1「次要遗留」段更新：all_unchecked 已实现。
- 需求文档 archive §5/§6 的 selection 枚举（只读历史不改），handoff 侧标注「已新增 all_unchecked」。
