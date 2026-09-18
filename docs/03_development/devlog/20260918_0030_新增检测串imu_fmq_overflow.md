# 20260918 新增检测串 imu fmq overflow f=

## 任务（Task）

依据 ADR-014 可扩展性，录像（video）与推流（rtmp）过程新增检测关键字符串 `imu fmq overflow f=`。

## 改动（Changed）

纯数据改动，业务代码零改动：

1. `ATS/drivers/detect_strings.py` 的 `DETECT_STRINGS` 追加 `"imu_fmq_overflow": DetectString("imu_fmq_overflow", r"imu fmq overflow f=", "imu fmq overflow f=")`。
2. `ATS/config/modules/video.yaml` 与 `rtmp.yaml` 的 `detect_strings` 由 `[tt_error]` 改为 `[tt_error, imu_fmq_overflow]`。

## 文件（Files）

- 修改：`ATS/drivers/detect_strings.py`、`ATS/config/modules/video.yaml`、`ATS/config/modules/rtmp.yaml`

## 原因（Reason）

用户 2026-09-18 需求：录像/推流过程新增检测该字符串（IMU FMQ 溢出日志）。完全按用户给的字符串（小写、含空格、`=` 结尾）；`=` 后实际有数字但不校验数字（字面串子串匹配即可命中 `... f=1234`）；纯字面串，跨 chunk 截断前缀自动推导生效，命中只收集不判 FAIL、追加 report detail（沿用 ADR-014 语义）。

## 验证（Verification）

- 配置加载：`video`/`rtmp` 的 `detect_strings == ["tt_error", "imu_fmq_overflow"]`。
- `_derive_splice_tails` 自动推导前缀，首条为 `imu fmq overflow f`。
- 命中 `f=1234`（数字不校验）、跨 chunk 截断还原 `... f=999`、大小写敏感不命中 `IMU FMQ OVERFLOW F=`、与 `tt_error` 多串并存——全 PASS。
- `py_compile` + `--list-modules` + `--dry-run` 无 import 破坏。

## 已知限制（Known limitation）

- 待真机确认该字符串在固件日志中的实际形态（用户已拍板字符串与不校验数字，但真机样本待补）。
