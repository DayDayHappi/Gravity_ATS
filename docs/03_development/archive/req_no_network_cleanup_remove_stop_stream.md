# 修改请求：no_network 场景 cleanup 移除冗余 stop_stream

> 提出方：Document Agent（真机验证后发现，交由 Code Agent 实施）
> 状态：已实施（devlog `20260916_0001`）
> 日期：2026-09-16

## 1. 背景

`no_network` 场景（devlog `20260916_0000`）已通过真机验证。检查发现其 cleanup 配置存在冗余：

```yaml
  cleanup:
    - stop_stream
    - close_serial
```

## 2. 问题

`no_network` 场景**不推流**（tasks 为 emmc/photo/video，无 rtmp task）。cleanup 的
`stop_stream` 会向串口发 `rtmp_video_stop` 并等 `Push Stop|Stop requested`，固件未推流时
大概率无此回显 → 空等约 8s 超时（异常被 `scenario_manager` cleanup 吞掉，无害但每次运行
浪费约 8 秒）。

## 3. 需求

把 `ATS/config/scenarios/no_network.yaml` 的 cleanup 改为只留 `close_serial`：

```yaml
  cleanup:
    - close_serial
```

移除 `- stop_stream`。

## 4. 边界

- **纯配置改动**，不改任何 `.py`、不改模块行为。
- 不影响其它场景（normal/stress/aging 等仍推流，其 `stop_stream` 保留）。
- `preview.enabled: false`，本来也没有 `preview_stop`，无需补。

## 5. 验收标准

- `python3 -m ATS.main --scenario no_network` 运行结束时，cleanup 日志**不再出现**
  `[cleanup] stop_stream`，直接 `[cleanup] close_serial`。
- `--list-scenarios` 仍能看到 `no_network`。

## 6. 留痕（工程红线）

- 改配置后需在 `docs/03_development/devlog/` 新建记录并更新其 README 索引
  （可合并进本次修改的 devlog，或单独一条）。
