# BUG-003：FTP 复用连接导致下载失败

## Problem

拍照/录像后 FTP 下载失败。

## Root Cause

板端 FTP 服务端 3s 空闲即断会话，旧代码缓存复用连接，下载时连接已失效。

## Solution

每次下载前重建独立连接（connect 恢复工作目录 + 关旧 socket），不再探测/复用旧连接；数据连接由主动模式每次换新端口。

## Verification

下载恢复正常。

## 关联

- devlog：`20260817_2241_ftp每次下载前重建连接_应对3s空闲超时.md`
- ADR-003
