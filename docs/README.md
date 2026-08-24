# 文档导航（Docs README）

> 本文件是文档知识库的**唯一导航入口**。Code Agent 只需读本文件，再按任务类型决定读哪些文件，**不要全量扫描**。

## 项目是什么

为 **VX100 EVB 板**开发的上位机自动化测试脚本（串口控制 + WiFi/FTP/RTMP 验证），详见 [00_project/overview.md](00_project/overview.md)。

## 按任务类型导航

### 接手项目（第一次接触）

1. [00_project/overview.md](00_project/overview.md) — 项目是什么
2. [01_architecture/system_architecture.md](01_architecture/system_architecture.md) — 架构分层
3. [05_handoff/current_status.md](05_handoff/current_status.md) — 当前状态
4. [05_handoff/next_step.md](05_handoff/next_step.md) — 该干什么

### 普通代码修改

1. [00_project/overview.md](00_project/overview.md)
2. [01_architecture/module_design.md](01_architecture/module_design.md)（对应模块）
3. 对应代码

### 架构修改

1. `00_project/` + `01_architecture/` 全部
2. [02_design/decision_record/](02_design/decision_record/) 相关 ADR

### Bug 修复

1. [01_architecture/module_design.md](01_architecture/module_design.md)（对应模块）
2. [03_development/bugfix/](03_development/bugfix/) 相关记录
3. 代码

## 目录结构

| 目录 | 内容 | 何时读 |
|------|------|--------|
| `00_project/` | 项目定位 / 术语 / 路线图 | 接手时 |
| `01_architecture/` | 分层 / 模块职责 / 数据流 / 接口 | 改代码前 |
| `02_design/` | ADR 设计决策 | 架构修改时 |
| `03_development/` | devlog 历史 + bugfix + archive | 排查历史时 |
| `04_testing/` | 测试策略 / 用例 | 验证时 |
| `05_handoff/` | 当前状态 / 环境 / 已知问题 / 下一步 | 接手时 |

## 红线速记

- **改代码必留痕**：在 `03_development/devlog/` 新建 `<YYYYMMDD>_<HHMM>_<描述>.md` 并更新其 README 索引。
- **模块红线**：模块只实现一次测试动作 + 参数接口，循环/重复/时长由 Scenario/Runner 驱动。
- **ftp_server 只发一次**；ftp 每次下载前重建连接。
- **配置三层别放错**：环境→system.yaml，模块参数→modules/*.yaml，流程→scenarios/*.yaml。
