# BUG-004：RTMP 探测失败（关键帧稀疏超时）

## Problem

RTMP 推流后 ffprobe 探测超时失败。

## Root Cause

板子推 1080p 编码慢 + FTP 刷屏抢 CPU → 关键帧 IDR 稀疏（约 600 帧/57s 一个），ffprobe 默认超时等不到 IDR。

## Solution

`-rw_timeout` 3s→15s、`analyzeduration`/`probesize` 放宽、重试加大，耐心等 IDR。

## Verification

探测成功。

## 关联

- devlog：`20260817_0203_RTMP探测失败_板子编码慢关键帧稀疏加大超时.md`
- ADR-004
