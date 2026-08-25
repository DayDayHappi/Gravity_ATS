"""模块基类与注册机制（解耦核心）。

设计要点：
- 每个功能模块继承 ``TestModule``，实现 ``run()``；``name`` 由 ``@register("xxx")`` 注入。
- ``@register("wifi")`` 装饰器把模块注册到全局表，runner 按名字查找、按 scenario 顺序执行。
- 模块只通过 ``ctx``（共享上下文）和 ``console``（串口）与其他模块交互，
  不直接 import 其他模块 -> 增删模块不影响既有模块。
- 模块只负责「怎么测」（一次测试动作 + 参数接口）；执行多少次/循环多久由
  scenario（config/scenarios/*.yaml）+ runner 控制，模块内**不写** for 循环。

新增一个测试项的步骤：
1. 在 ``modules/`` 新建文件，定义 ``class XxxModule(TestModule)`` + ``@register("xxx")``。
2. 在 ``config/modules/`` 新增 ``xxx.yaml``（能力参数）。
3. 在 ``config/scenarios/<场景>.yaml`` 的 tasks 加一行 ``- module: xxx``。
4. 无需改 core 或其他模块。
"""
from ..core.result import TestResult


# 全局模块注册表：name -> TestModule 子类
_REGISTRY = {}


def register(name: str):
    """类装饰器：把模块类注册到全局表。

    Args:
        name: 模块名，需与 scenario tasks 里的 ``module:`` 名字一致。
    """
    def deco(cls):
        if name in _REGISTRY:
            raise ValueError(f"模块名冲突，已注册: {name}")
        cls.name = name
        _REGISTRY[name] = cls
        return cls
    return deco


def get_module_cls(name: str):
    """按名字取已注册的模块类；未注册返回 None。"""
    return _REGISTRY.get(name)


def list_modules() -> list:
    """列出所有已注册模块 (name, cls)。"""
    return sorted(_REGISTRY.items())


class TestModule:
    """所有功能模块的基类。

    子类需设置：
        name:   模块名（由 @register 注入，子类不必显式声明）
        depends: 运行时 task 间 fail-fast 依赖（当前三场景均无此用法，字段保留但空；
                 逻辑依赖由 Scenario prepare 编排 + module_design.md 表达，见 ADR-009）

    子类可覆盖：
        setup():    前置（如启动 PC 端服务）
        run():      主逻辑，返回 TestResult 或 list[TestResult]
        teardown(): 后置清理
    """

    name: str = ""
    depends: list = []
    duration_key: str = None   # 子类声明「持续类」参数 key，供 scenario 的 task.duration 快捷覆盖

    def __init__(self, config: dict):
        """config 为该模块的能力参数（来自 config/modules/<name>.yaml）。"""
        self.config = config or {}

    def setup(self, ctx, console):
        """前置钩子，默认无操作。"""
        pass

    def run(self, ctx, console, params=None):
        """主逻辑，子类必须实现。

        Args:
            ctx: 共享上下文。
            console: 串口控制台。
            params: 运行时参数覆盖（scenario override + CLI），覆盖 self.config。
                子类开头用 ``self.config = self._merge(params)`` 合并即可，后续
                ``self.config.get(...)`` 自动生效。

        Returns:
            TestResult 或 list[TestResult]。
        """
        raise NotImplementedError(f"{self.__class__.__name__} 未实现 run()")

    def _merge(self, params: dict = None) -> dict:
        """合并模块默认参数与运行时覆盖（覆盖优先），返回新 dict。

        示例：``self.config = self._merge(params)``。
        """
        return {**(self.config or {}), **(params or {})}

    def teardown(self, ctx, console):
        """后置钩子，默认无操作。"""
        pass

    # ---------- 便捷工厂 ----------

    def _pass(self, msg: str = "") -> TestResult:
        return TestResult(name=self.name, module=self.name, status="PASS", message=msg)

    def _fail(self, msg: str = "", detail: str = "") -> TestResult:
        return TestResult(name=self.name, module=self.name, status="FAIL",
                          message=msg, detail=detail)

    def _skip(self, msg: str = "") -> TestResult:
        return TestResult(name=self.name, module=self.name, status="SKIP", message=msg)

    def _error(self, msg: str = "", detail: str = "") -> TestResult:
        return TestResult(name=self.name, module=self.name, status="ERROR",
                          message=msg, detail=detail)
