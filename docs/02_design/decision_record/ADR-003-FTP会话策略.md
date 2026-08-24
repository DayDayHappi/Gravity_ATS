# ADR-003：FTP 会话策略三原则

## Background

板端 RT-Thread 自带 FTP 服务有重大限制：摄像头操作后崩溃循环（`service go wrong`）、3s 空闲即断会话、只支持主动模式（不支持 PASV/NLST/STOR/SIZE）。

## Problem

在固件不稳定的前提下，如何稳定使用 FTP 传输产物。

## Decision

三原则：

1. **`ftp_server` 全程只发一次**（幂等标志）。重发触发固件崩溃循环刷屏。
2. **冷启动分两阶段**：`Ftp server init success` ≠ 已 listen，要等 `service launched success`（约 3~4s）才能 connect。
3. **每次下载前重建连接**：不缓存/复用（服务端 3s 空闲断会话）；新 socket → 登录 → cwd 根目录。

另：只支持主动模式（PORT），需 PC 防火墙放行入站高位端口；`LIST <path>` 忽略路径（先 CWD 再无参 LIST）；`size` 用 LIST 父目录解析；上传不可用。

## Alternative

- 每次 force 重启 ftp_server：触发崩溃循环，废弃。
- 缓存复用连接：3s 空闲超时导致下载失败，废弃。

## Impact

`modules/ftp`、`modules/photo`、`modules/video`、`drivers/ftp_client`。

## Status

Accepted
