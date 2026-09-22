"""恢复后端抽象（RecoveryBackend，ADR-016）。

统一恢复能力接口：``name`` / ``available(ctx)`` / ``recover(ctx)``。
Coordinator 只调用 ``backend.recover()``，更换电源机制（USB Relay / Network PDU /
Soft Reset）无需修改 Monitor、Runner 或业务模块。

注册：各后端文件通过 ``@register_backend`` 装饰器注册；``__init__.py`` 负责
import 各后端模块触发注册（本文件不 import 后端，避免循环依赖）。
"""


class RecoveryBackendUnavailable(Exception):
    """恢复后端不可用（能力关闭或探测失败），禁止静默 fallback。"""


class RecoveryBackend:
    """恢复后端基类。子类实现 ``name`` 属性与 ``recover()``。"""

    name = "base"

    def available(self, ctx) -> bool:
        """该后端在当前 ctx 下是否可用。默认 True，子类覆盖。"""
        return True

    def recover(self, ctx):
        """执行恢复动作。子类必须实现，返回恢复结果描述。"""
        raise NotImplementedError

    def __repr__(self):
        return f"<RecoveryBackend:{self.name}>"


_REGISTRY = {}


def register_backend(name):
    """装饰器：注册恢复后端。"""
    def deco(cls):
        cls.name = name
        _REGISTRY[name] = cls
        return cls
    return deco


def get_backend(name: str):
    """按名字取恢复后端类；未注册返回 None。"""
    return _REGISTRY.get(name)


def create_backend(name: str, config: dict = None):
    """按名字实例化恢复后端；未注册返回 None。"""
    cls = get_backend(name)
    if cls is None:
        return None
    return cls(config or {})
