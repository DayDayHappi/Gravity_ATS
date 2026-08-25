# 修正 base 模块 docstring 语义（对齐 ADR-009）

## 日期
2026-08-24

## 变更来源
`docs/05_handoff/next_step.md` P1：`ATS/modules/base.py` docstring 过时，与 ADR-005/009 不符。

## 做了什么
纯 docstring 修正，不改任何行为/接口：

| 位置 | 改动前 | 改动后 |
|------|--------|--------|
| 模块 docstring（L4） | 实现 ``run()``，声明 ``name`` 和 ``depends`` | 实现 ``run()``；``name`` 由 ``@register("xxx")`` 注入 |
| TestModule docstring `depends:`（L54） | 依赖的模块名列表（runner 据此拓扑排序） | 运行时 task 间 fail-fast 依赖（当前三场景均无此用法，字段保留但空；逻辑依赖由 Scenario prepare 编排 + module_design.md 表达，见 ADR-009） |

`name` / `depends` 类属性、`run()`/`setup()`/`teardown()` 方法签名、`@register` 装饰器均不变。

## 改了哪些文件
- `ATS/modules/base.py`（仅 docstring，2 处）

## 如何验证
1. `python3 -c "from ATS.modules import base"` → import OK。
2. `grep -n "拓扑排序" ATS/modules/base.py` → 无残留。
3. `hasattr(TestModule, "depends")` → True（字段保留但空，符合 ADR-009）。

## 已知遗留
无。本修正同步解决了 `20260824_0250_depends字段清理.md` 中「待 Document Agent」的 base.py docstring 过时项。
