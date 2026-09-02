# 项目总览（Project Overview）

> 本文档回答「这个项目是什么、解决什么问题」。新接手者从这里开始。

## 1. 项目目的（Project Purpose）

为 **VX100 EVB 板**（双核异构 RISC-V，运行 RT-Thread，提供 msh shell）开发的**上位机自动化测试脚本**，替代人工手动测试，用于功能验证与产测。

## 2. 主要功能（Main Function）

PC 通过串口向 EVB 下发命令，通过 WiFi/FTP/RTMP 验证功能产物，自动执行并判定以下测试链路，生成报告：

```
模块（8 个，代码保留）：wifi_check / wifi_scan / wifi_join / emmc / ftp / photo / video / rtmp
normal 执行：prepare（wifi_connect 收敛器连 WiFi + ftp_ready 启 FTP）
             → tasks（emmc → photo → video → rtmp，4 项）
```

入口：`python3 -m ATS.main --scenario <name>`（默认 `normal`）。

## 3. 支持场景（Supported Scenario）

- **normal**：WiFi/FTP 由 prepare 准备（wifi_connect 收敛器 + ftp_ready），tasks 4 项（emmc/photo/video/rtmp），向后兼容的默认场景。
- **stress**：photo×50 + video 180s + rtmp 600s，整轮循环 3 次（压测）。
- **aging**：photo×10 + rtmp 600s，限时 2h 循环（老化）。

## 4. 系统边界（System Boundary）

**负责**：串口命令交互与响应解析、功能产物验证（照片/视频/推流）、测试编排与报告生成。

**不负责**：
- 多 EVB 并行测试（预留接口，未实现）
- 产线烧录（Flash / eFuse，属产测工具范畴）
- EVB 电源自动控制（第一阶段人工上电）
- 负向测试（第二阶段）

## 5. 高层架构（High Level Architecture）

```
PC (Python) ──串口 2000000bps──>  EVB (msh shell)
     │                                │ 摄像头
     │  WiFi/FTP/RTMP                 │
     ◄────────────────────────────────┘
```

系统采用 **scenario 驱动的分层执行模型**，详见 [../01_architecture/system_architecture.md](../01_architecture/system_architecture.md)。

## 6. 分支约定（Branch Convention）

- **主分支 = `new_arch`**：项目活跃开发与稳定代码的汇聚分支，所有改动默认基于 `new_arch`。
- `main`：仓库默认分支，保留但**非**本项目开发主线。
- 功能/验证分支（如 `testvideo`）从 `new_arch` 拉取，完成后合回 `new_arch`。
