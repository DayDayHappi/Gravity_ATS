# ADR-004：RTMP 验证判据（ffprobe 实时探测 + heartbeat）

## Background

RTMP 验证需要同时回答两个问题：流是否真实到达且可解码；推流过程中是否持续稳定。

## Problem

单一判据不够——只查「连接存在」验证不了流内容；只查一次验证不了持续稳定性。

## Decision

- **主判据**：ffprobe 实时探测 `rtmp://<pc_ip>/live/cam`，探到 h264 + 分辨率即 PASS。
- **持续检测**：独立 monitor 订阅串口原始数据，用板端 `[RTMP] f_index` 日志作 heartbeat（正常约 2~4s 一条），超 `heartbeat_timeout`（60s）无心跳判推流异常，提前 FAIL。
- **时序**：ffprobe 探测必须在 `rtmp_video_stop` 之前（探测的是实时流）。
- ffplay 仅可选画面确认（无 DISPLAY 自动跳过），不影响判据。

## Alternative

- nginx 统计接口查连接：验证不了流内容。
- ffmpeg 拉流存盘：重，且非实时判据。

## Impact

`modules/rtmp`、`modules/rtmp_monitor`、`drivers/rtmp_receiver`、`drivers/rtmp_server`。

## Status

Accepted
