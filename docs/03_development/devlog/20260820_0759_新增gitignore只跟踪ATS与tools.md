# 新增 .gitignore：仓库只跟踪 ATS 与 tools

**日期**: 2026-08-20
**改动范围**: 新增 `.gitignore`；`git rm --cached` 取消跟踪一批已提交文件

---

## 一、问题描述

仓库历史里混入了大量运行产物与二进制：`logs/`(583 文件)、`reports/`(285 文件)、
`ATS/` 下 26 个 `.pyc` 字节码，加上 `doc/ handoff/ res/ .claude/` 及根目录杂项，
导致每次运行测试都会产生海量无关 diff，污染提交。

## 二、修复内容

1. 新增 `.gitignore`：忽略 `logs/ reports/ doc/ handoff/ res/ .claude/`、根目录
   `migrate.sh 迁移指南.md all_source.txt auto.crt auto.key`、`__pycache__/ *.py[cod]`。
2. `git rm -r --cached` 取消跟踪上述文件（**本地文件均保留**，仅 git 不再追踪改动）。
3. 保留跟踪：`ATS/`（源码 28 文件）与 `tools/`（内置 ffmpeg 二进制，离线运行必需）。

## 三、验证结果

- `git ls-files` 剩余：`ATS/` 28 + `tools/` 6 + `.gitignore` 1。
- `git status` 干净，后续运行产生的 logs/reports 不再出现在 git status。

## 四、还会再有吗

- `.gitignore` 对**已跟踪文件无效**，故需配合 `git rm --cached` 才能生效；本此已一并处理。
- `tools/` 二进制保留跟踪（422MB），换机器 clone 后可直接离线运行；若后续嫌仓库大，
  可再决定是否改为外置下载。

## 五、经验沉淀

- 想"只跟踪某目录"，光加 `.gitignore` 不够，历史已跟踪文件必须 `git rm -r --cached`
  解除索引（本地不删），否则 ignore 规则对其不生效。
