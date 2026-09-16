# 无网络场景 cleanup 移除冗余 stop_stream

## Date / Task

- 日期：2026-09-16
- 任务：`no_network.yaml` 的 cleanup 移除冗余 `stop_stream`，只保留 `close_serial`
- 来源：Document Agent 修改请求（archive request）

## Changed

- `ATS/config/scenarios/no_network.yaml`：cleanup 由 `[stop_stream, close_serial]`
  改为 `[close_serial]`。

## Files

- `ATS/config/scenarios/no_network.yaml`

## Reason

无网络场景不推流（tasks 无 rtmp），却发 `rtmp_video_stop` 会空等约 8s 超时
（`RTMP_STOP_TIMEOUT = 8.0`），异常虽被吞、无害但浪费时间。场景不推流就无需兜底停推。

## Verification

- `load_scenario('no_network')` → `cleanup == ['close_serial']`，断言通过
- 纯配置改动，未触及任何 `.py`，不影响其它推流场景

## Known limitation

- 无网络场景整体仍待真机验证（与此前同）。
