# Windows CLI exe 打包发布方案（feature/windows-cli）

> 本文件是 `feature/windows-cli` **分支专属**的打包发布实施方案，短期不合入 `new_arch`。
> 属**实现级**（Level 1~2，不新增架构层级），**不需要 ADR**；改动涉及 `ATS/` 源码，按红线必须 devlog 留痕。
> 前置设计见 [windows_cli_port_plan.md](windows_cli_port_plan.md)。
>
> **状态：已实施完成**（devlog `20261027_1112`），`dist/AtsCli_release.zip` 已产出并通过 exe 冒烟（`--list-scenarios` / `--dry-run`）。
> 遗留：真实干净 Windows 机器（无 Python）端到端冒烟仍待执行（见 §8）。

## 1. 目标

把脚本打包成 Windows 自包含 exe，同步给**未安装 Python / venv / pip 依赖**的干净机器使用，同时保留「用户可自行编辑 scenario 配置」的能力。

## 2. 目标机依赖边界（结论，先明确）

| 依赖 | 是否随 exe 自带 | 处理 |
|------|---------------|------|
| Python 解释器 + 标准库 | ✅ PyInstaller 自动打进 | 目标机**免装** Python |
| 纯 Python 库（`pyserial`/`PyYAML`/`jinja2`） | ✅ 自动打进 | 目标机**免装**、免 venv、免 `pip install` |
| **ffprobe / ffmpeg / ffplay** | ❌ 不会（是 `subprocess` 调用的**原生可执行文件**，不是 Python import） | 随包放 `tools/ffmpeg/*.exe`，或目标机 PATH 已有 |
| nginx-rtmp（1935） | ❌ 不会（独立服务程序） | 需要 RTMP 测试时另装/自带 |
| USB-UART 串口驱动 | ❌ 不会（OS 驱动） | 插板子前另装 |

`.venv-cli` 与 `scripts/setup_windows.ps1` 的 Step-Python / Step-Venv 是**开发/打包机**环境，与目标机无关。

## 3. 核心设计：config 走「exe 同级可编辑目录」

PyInstaller 打包后，`ATS/core/config.py` 当前的

```python
CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
```

会指向临时解包目录 `_MEIPASS\ATS\config`（**只读、每次运行可能变化**），用户无法稳定编辑。
因此发布版把 `config/` 作为 **exe 同级的独立目录**随包分发，用户改场景 = 用文本编辑器改该目录下的 YAML。

### 3.1 用户怎么编辑 scenario

- 改流程：编辑 `config/scenarios/<场景名>.yaml`（tasks 顺序 / repeat / duration / override / loop）。
- 新增场景：在该目录新建 `<name>.yaml`（文件名即 `--scenario` 的取值），必须含 `scenario:` 段。
- 改模块参数：编辑 `config/modules/<module>.yaml`（依赖下面 §5 的 T2 透传修复才生效）。
- 改环境参数：编辑 `config/system.yaml`（串口 / WiFi / pc.ip）。

### 3.2 启动方式（argparse 参数原样保留）

exe 入口即 `ATS.main.main()`，所有现有 CLI 参数在 exe 下照常可用：

```powershell
.\AtsCli.exe --scenario stress --no-interactive-wifi
.\AtsCli.exe --config-dir .\config --scenario normal   # 显式指定配置目录
.\AtsCli.exe --list-scenarios
```

**红线**：不要打成 `--windowed/--noconsole`。脚本有 `input()` 交互（WiFi 选择、结束 problem 询问），必须是控制台程序。

**分发建议**：每场景配一个启动器 bat 固定常用参数（用户免记参数、免踩 `python3` 别名坑）：

```bat
:: run_stress.bat
@echo off
".\AtsCli.exe" --scenario stress --no-interactive-wifi
```

强烈建议把 `--no-interactive-wifi` 封进启动器，否则他人运行会停在 `是否连接默认 WiFi? [Y/n]` 交互。

## 4. 发布目录结构（onedir）

```
发布包（整个文件夹 zip 给用户）
├─ AtsCli.exe              # PyInstaller onedir 主程序
├─ _internal/              # PyInstaller 运行时（自动生成，勿动）
├─ config/                 # ★ 可编辑配置（用户只改这里）
│  ├─ system.yaml
│  ├─ modules/
│  └─ scenarios/
├─ tools/ffmpeg/           # ffprobe.exe / ffmpeg.exe / ffplay.exe（随包，免下载）
├─ run_normal.bat
├─ run_stress.bat
├─ run_aging.bat
└─ 使用说明.txt
```

- **onedir 而非 onefile**：外部 `config/` 与 `tools/ffmpeg/` 本就在 exe 外，onedir 启动快、无临时解包问题，且「exe 同级」语义清晰。
- `tools/ffmpeg/` 的查找已由 `ATS/platform/resources.py` 支持：frozen 时以 `sys.executable` 所在目录为根，自动找 `tools/ffmpeg/*.exe`，找不到再回退 PATH。**打包侧无需改代码，只需把三件套放进该目录。**

## 5. Code Agent 待办（改动清单）

> 均为实现级改动，不碰架构分层、不碰模块红线、不碰 ADR-011 协议集中化。

### T1（核心）config 默认目录 frozen 解析

**文件**：`ATS/core/config.py`（`CONFIG_DIR` 定义处，L28）。

**现状**：`CONFIG_DIR` 用 `__file__` 向上两级，frozen 下指向 `_MEIPASS\ATS\config`。

**要求**：改为 frozen 感知，优先级：

1. 显式 `--config-dir` 传入 → 用它（现有逻辑已支持，不动）。
2. `sys.frozen` 为真 → 优先 `Path(sys.executable).parent / "config"`（exe 同级，可编辑）；若该目录不存在或缺 `system.yaml`，回退到打包内置的 `_MEIPASS/ATS/config`（只读备份，保证首次运行 `--list-scenarios` 等可用）。
3. 非 frozen → 维持现有 `__file__` 派生逻辑（不影响 Linux 主线）。

可复用 `ATS/platform/resources.py` 的 frozen 检测模式（`getattr(sys, "frozen", False)` + `sys.executable`）。

### T2（核心）`config_dir` 透传缺口

**现状**：`--config-dir` 只对 `system.yaml` 与 `scenarios/*.yaml` 生效；`modules/*.yaml` 的多处加载**未透传** `config_dir`，frozen 下会读错目录（或读不到）。

**根因证据**（已核对源码）：

| 位置 | 现状调用 | 后果 |
|------|---------|------|
| `core/runner.py` L112 | `load_module_config(task.module)` | 读 frozen 内置路径 |
| `core/scenario_manager.py` L450/L451 | `load_module_config("preview")` / `load_module_config("rtmp")` | 同上 |
| `core/scenario_manager.py` L514 | `load_module_config("board_health")` | 同上 |
| `modules/ftp.py` L93 | `load_module_config("ftp")` | 同上 |

**要求（最小透传）**：

1. `ScenarioManager.run()` 里设置 `ctx.config_dir = self.config_dir`（`self.config_dir` 已在 `__init__` 就绪）。
2. 上述 4 处调用改为从 `ctx` 取并传入：
   - `runner.py` L112 → `load_module_config(task.module, getattr(self.ctx, "config_dir", None))`（`self.ctx` 已存在）。
   - `scenario_manager.py` L450/451/514 → 动作函数签名已有 `ctx`，用 `getattr(ctx, "config_dir", None)`。
   - `modules/ftp.py` L93 → `start_ftp(ctx, console)` 已有 `ctx`，用 `getattr(ctx, "config_dir", None)`。

> 说明：`main.py` L71 的 `load_module_config("rtmp", config_dir)` 已正确透传，无需改。

### T3（次要）`portal_upload.py` 工程根 frozen 解析

**文件**：`ATS/application/portal_upload.py` L40。

**现状**：

```python
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

frozen 下指向 `_MEIPASS`，导致 `system.yaml` 里 `upload.token` / `ca_cert` 的相对路径锚定错。

**要求**：frozen 时改为 `Path(sys.executable).parent`；非 frozen 维持现状。用途与 `_resolve_from_project_root` 一致（相对路径锚定 exe 同级）。

### T4（打包）PyInstaller 隐藏导入

`ATS/modules/__init__.py` 通过 `importlib.import_module("ATS.modules")` 动态导入子模块（`runner.py` L56、`main.py` L89/L252），PyInstaller 静态分析**很可能漏掉**，尤其 `ATS.modules.utest` 是包。若漏掉，exe 里模块注册表为空，所有 task 报「未注册模块」。

**要求**：打包命令/spec 加入：

```
--collect-submodules ATS
--hidden-import jinja2
--hidden-import serial.tools.list_ports
```

并加 `--add-data "ATS/config;ATS/config"`（把内置配置作为 `_MEIPASS/ATS/config` 只读备份，供 T1 回退）。

### T5（发布配置）分发前收敛 system.yaml

当前 `ATS/config/system.yaml` 的 `upload.enabled: true` 且 `server` 指向内网 `10.1.64.183`，`ca_cert` 指向本机路径。**直接分发会向你的内网打上传请求、暴露 token/证书路径。**

**要求**：打包发布版本把 `upload.enabled` 置 `false`（或提供一份「发布用 system.yaml」）；`upload.token` / `ca_cert` 等本机敏感项不随包分发。

### T6（打包）spec / 脚本 + 目录组装

产出建议（Code Agent 自行实现，以下为规格）：

1. PyInstaller onedir，入口 `ATS/main.py`，`--name AtsCli`，控制台模式。
2. 组装发布目录：`dist/AtsCli/` 旁放 `config/`（**不要**用 `_internal` 里的那份作为用户编辑对象）、`tools/ffmpeg/`（三件套）、启动器 bat、使用说明。
3. 交付物为整个 `AtsCli/` 文件夹的 zip。

### T7（文档）启动器 + 使用说明

- 生成 `run_normal.bat` / `run_stress.bat` / `run_aging.bat`（封装 `--no-interactive-wifi`）。
- 在发布包内附「使用说明.txt」：改 scenario 的位置、启动命令、ffmpeg 依赖、nginx-rtmp 说明。
- 同步更新分支文档 [windows_cli_启动指南.md](../05_handoff/windows_cli_启动指南.md) 增「发布版（exe）使用」一节。

## 6. 验证清单（Code Agent 自测）

- [ ] 干净 Windows（无 Python）双击 `run_stress.bat` 可跑，`--dry-run` 通过。
- [ ] `--list-scenarios` 列出的是 **exe 同级 `config/scenarios/`** 的文件（不是 `_MEIPASS`）。
- [ ] 用户修改 `config/scenarios/stress.yaml`（如改 repeat）后重跑生效。
- [ ] 用户修改 `config/modules/video.yaml` 参数后重跑生效（**验证 T2**）。
- [ ] 用户新增 `config/scenarios/foo.yaml` 后 `--scenario foo` 可识别。
- [ ] `ffprobe` 从 `tools/ffmpeg/` 命中（跑含 rtmp 场景或看 run.log 的查找路径）。
- [ ] 显式 `--config-dir` 覆盖仍优先于 exe 同级目录。
- [ ] 非 frozen 路径（`python -m ATS.main`）回归不受 T1/T2 影响。

## 7. 红线确认

- 改动涉及 `ATS/` 源码 → **必须**在 `docs/03_development/devlog/` 新建 devlog 并更新其 README 索引。
- 不动 `config → ScenarioManager → Runner → Module → Driver` 分层；T1/T2/T3 是路径解析透传，不改变任何测试语义。
- 不改任何模块协议字符串 / 判据（ADR-011 边界不动）。
- 不新增 ADR（实现级）；合 `new_arch` 时若需正式化，由 Document Agent 再评估。

## 8. 实施结果与遗留（devlog `20261027_1112`）

- **已落地**：T1~T7 全部实施，全量 69 unittest 通过；本机 exe 冒烟通过（`--list-scenarios` 列出 12 场景、`--dry-run` 识别 emmc/photo/video/rtmp 模块，证明 `--collect-submodules ATS` 隐藏导入生效）。
- **已修复的回归**：构建脚本曾存在「无 pyyaml 时静默跳过 system.yaml 收敛 → 敏感项泄漏」缺陷，已改 fail-closed（缺 pyyaml 直接报错退出）。
- **遗留（不阻塞分发）**：未在真正干净 Windows（无 Python）机器做端到端冒烟；`--power-stress` 入口实现文件缺失（见 [known_issue.md](../05_handoff/known_issue.md)），仅降级报错。
