"""配置加载与校验。

职责：
1. 读取 YAML 配置文件（默认 ``config/test_config.yaml``）。
2. ``${ENV_VAR}`` 语法替换：敏感字段从环境变量读取，未设置则保留原值并警告。
3. 基础 schema 校验：必填项、类型检查，配置错在启动阶段即报错退出（MAI-004）。
4. CLI 参数覆盖：命令行参数优先级高于配置文件。

配置是"数据驱动"的核心：增删测试项、改流程，大多只动 YAML，不改代码。
"""
import os
import re
import copy

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(Exception):
    """配置错误（缺失/类型不对/校验失败）。"""


def _expand_env(value):
    """递归替换字符串中的 ``${ENV_VAR}``。

    环境变量未设置时保留原 ``${VAR}`` 字面量（调用方可据此判断是否需要交互输入）。
    """
    if isinstance(value, str):
        def repl(m):
            name = m.group(1)
            return os.environ.get(name, m.group(0))  # 未设置保留原样
        return _ENV_RE.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


# 基础 schema：section -> {key: (类型, 是否必填)}
# 仅校验框架运行必需的字段；模块自有字段由模块自行读取与校验
_SCHEMA = {
    "serial": {
        "port": (str, True),
        "baudrate": (int, True),
        "timeout": ((int, float), False),
    },
    "wifi": {
        "default_ssid": (str, True),
    },
    "test": {
        "enabled_modules": (list, True),
    },
}


def _validate(cfg: dict):
    """按 schema 做基础校验，失败抛 ConfigError。"""
    if not isinstance(cfg, dict):
        raise ConfigError("配置根必须是字典")
    for section, fields in _SCHEMA.items():
        if section not in cfg:
            raise ConfigError(f"缺少必填配置段: {section}")
        for key, (typ, required) in fields.items():
            if key not in cfg[section]:
                if required:
                    raise ConfigError(f"配置段 [{section}] 缺少必填项: {key}")
                continue
            val = cfg[section][key]
            # typ 可能是元组（多类型允许）
            types = typ if isinstance(typ, tuple) else (typ,)
            if not any(isinstance(val, t) for t in types):
                raise ConfigError(
                    f"配置项 [{section}].{key} 类型应为 {typ}，实际 {type(val).__name__}"
                )
    # enabled_modules 不能为空
    if not cfg["test"]["enabled_modules"]:
        raise ConfigError("test.enabled_modules 不能为空")


def load_config(path: str) -> dict:
    """加载并校验配置文件。

    Args:
        path: YAML 配置文件路径。

    Returns:
        展开 ${ENV} 后的配置字典。

    Raises:
        ConfigError: 文件不存在/格式错误/校验失败。
    """
    if yaml is None:
        raise ConfigError("缺少 pyyaml 依赖，请先 pip install pyyaml")
    if not os.path.isfile(path):
        raise ConfigError(f"配置文件不存在: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML 解析失败: {e}")
    if not isinstance(raw, dict):
        raise ConfigError("配置文件根必须是字典")
    cfg = _expand_env(raw)
    _validate(cfg)
    return cfg


def apply_overrides(cfg: dict, overrides: dict) -> dict:
    """用 CLI 覆盖项合并进配置（覆盖项优先）。

    overrides 用扁平点号 key，如 ``{"serial.port": "/dev/ttyUSB1", "wifi.default_ssid": "X"}``。
    返回新的配置字典，不修改原 cfg。
    """
    out = copy.deepcopy(cfg)
    for dotted, val in overrides.items():
        if val is None:
            continue
        parts = dotted.split(".")
        node = out
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = val
    return out
