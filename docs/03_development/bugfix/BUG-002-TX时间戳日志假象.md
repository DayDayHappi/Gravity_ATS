# BUG-002：TX 时间戳晚于 RX 的日志假象

## Problem

串口日志出现「先收后发」假象（RX 时间戳早于 TX），干扰排查。

## Root Cause

`_write_cmd` 的 TX 日志打在分片循环之后，分片 sleep 让 TX 时间戳后移到「发送完成」，晚于板子回显 RX。

## Solution

TX 日志移到分片循环前，记录「发送开始」时间。

## Verification

时间戳恢复正常先后顺序。

## 关联

- devlog：`20260820_0132_修复TX时间戳晚于RX的日志假象.md`
