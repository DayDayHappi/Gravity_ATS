"""模块基类与注册机制（解耦核心）。

设计要点：
- 每个功能模块继承 ``TestModule``，实现 ``run()``，声明 ``name`` 和 ``depends``。
- ``@register("wifi")`` 装饰器把模块注册到全局表，runner 按名字查找、按依赖排序。
- 模块只通过 ``ctx``（共享上下文）和 ``console``（串口）与其他模块交互，
  不直接 import 其他模块 -> 增删模块不影响既有模块。

新增一个测试项的步骤：
1. 在 ``modules/`` 新建文件，定义 ``class XxxModule(TestModule)`` + ``@register("xxx")``。
2. 在 ``config/test_config.yaml`` 的 ``enabled_modules`` 加一行 ``- xxx``。
3. 无需改 core 或其他模块。
"""
from ..core.result import TestResult


# 全局模块注册表：name -> TestModule 子类
_REGISTRY = {}


def register(name: str):
    """类装饰器：把模块类注册到全局表。

    Args:
        name: 模块名，需与 ``enabled_modules`` 中的名字一致。
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
        depends: 依赖的模块名列表（runner 据此拓扑排序）

    子类可覆盖：
        setup():    前置（如启动 PC 端服务）
        run():      主逻辑，返回 TestResult 或 list[TestResult]
        teardown(): 后置清理
    """

    name: str = ""
    depends: list = []

    def __init__(self, config: dict):
        """config 为该模块对应的配置段（runner 从总配置里切出来传入）。"""
        self.config = config or {}

    def setup(self, ctx, console):
        """前置钩子，默认无操作。"""
        pass

    def run(self, ctx, console):
        """主逻辑，子类必须实现。

        Returns:
            TestResult 或 list[TestResult]。
        """
        raise NotImplementedError(f"{self.__class__.__name__} 未实现 run()")

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
