# CLAUDE.md

VX100 EVB 上位机自动化测试脚本工程。入口：`python3 -m ATS.main --scenario <name>`（默认 `normal`）。

## Agent 角色选择（Agent Role Selection）

- 以 **Code Agent** 身份工作时，先读 `.claude/agents/code-agent.md`（代码实现者，只改源码/测试/devlog）。
- 以 **Document Agent** 身份工作时，先读 `.claude/agents/document-agent.md`（工程知识管理员，只改架构/设计/交接）。
- **不得混职责**：Code Agent 不碰架构/设计/交接文档，Document Agent 不碰源码。

## 文档管理（Document Management）

- 文档知识库在 `docs/`，唯一导航入口是 `docs/README.md`。任何 Agent 先读它，再按任务决定读哪些文件，不要全量扫描。
- 当以 **Document Agent** 身份工作时，必须先读 `.claude/agents/document-agent.md`，所有文档改动遵循该规则。
- 文档按生命周期分层，禁止混类：架构（稳定）→ `01_architecture/`，设计决策 → `02_design/`，历史 → `03_development/`，当前状态 → `05_handoff/`。

## 工程红线（所有 Agent 必守）

1. **改代码必留痕**：改 `ATS/` 代码必须在 `docs/03_development/devlog/` 新建 `<YYYYMMDD>_<HHMM>_<描述>.md` 并更新其 README 索引。
2. **模块红线**：模块只实现一次测试动作 + 参数接口；循环/重复/时长由 Scenario + Runner 驱动，模块内不得写 for 循环、不得感知场景类型。
3. **FTP 会话**：`ftp_server` 全程只发一次（重发触发固件崩溃）；每次下载前重建连接（服务端 3s 空闲断会话）。
4. **配置三层别放错**：环境（串口/WiFi/pc.ip）→ `config/system.yaml`；模块参数 → `config/modules/*.yaml`；流程/循环 → `config/scenarios/*.yaml`。
5. **哨兵 ≠ 业务完成**：异步命令的 expect 必须是真实业务字符串，不能是命令回显。
