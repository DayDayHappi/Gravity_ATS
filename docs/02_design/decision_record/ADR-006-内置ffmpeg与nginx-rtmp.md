# ADR-006：内置 ffmpeg + nginx-rtmp 离线依赖

## Background

RTMP 验证需要 ffmpeg/ffprobe；推流需要 PC 端服务端中转。离线环境无法 apt 安装依赖。

## Problem

在离线、依赖受限的产测环境下打通 RTMP。

## Decision

- **内置静态 ffmpeg/ffprobe/ffplay** 到 `tools/ffmpeg/`（离线可用，零代码改动，配置指向内置二进制）。
- **服务端改用系统 nginx-rtmp**（`application live`，监听 1935），脚本只查就绪（`check_ready`），不启停 nginx。
- **判据改 ffprobe 实时探测**（不存盘），去 MediaMTX。

## Alternative

- apt 安装 ffmpeg：离线不可用。
- MediaMTX 中转：曾出现 `too many reordered frames` 乱序帧问题，弃用。

## Impact

`tools/`、`drivers/rtmp_receiver`、`drivers/rtmp_server`。

## Status

Accepted
