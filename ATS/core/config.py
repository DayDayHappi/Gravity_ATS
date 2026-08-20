"""配置加载与校验（拆分版）。

配置体系拆为三层，各司其职：
- ``config/system.yaml``：系统/环境级（串口、PC 地址、网络环境、报告、执行策略）。
- ``config/modules/<name>.yaml``：模块能力参数（每模块一个文件）。
- ``config/scenarios/<name>.yaml``：测试策略（流程/组合/循环/持续时间）。

职责：
1. 读取 YAML，``${ENV_VAR}`` 语法替换（敏感字段从环境变量读，未设保留原值）。
2. 基础 schema 校验（system 必填段、scenario 结构）。
3. CLI 参数覆盖（点号 key，优先级高于配置）。

配置是「数据驱动」核心：增删测试项/改流程，大多只动 YAML，不改代码。
"""
import os
import re
import copy
import glob

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# 默认配置目录：ATS/config
CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")

# 模块名 -> 配置文件名（wifi_check/scan/join 共用一个 wifi.yaml）
_MODULE_FILE_MAP = {
    "wifi_check": "wifi", "wifi_scan": "wifi", "wifi_join": "wifi",
    "emmc": "emmc", "ftp": "ftp", "photo": "photo", "video": "video", "rtmp": "rtmp",
}


class ConfigError(Exception):
    """配置错误（缺失/类型不对/校验失败）。"""


def _expand_env(value):
    """递归替换字符串中的 ``${ENV_VAR}``。

    环境变量未设置时保留原 ``${VAR}`` 字面量（调用方可据此判断是否需要交互输入）。
    """
    if isinstance(value, str):
        def repl(m):
            name = m.group(1)
            return os.environ.get(name, m.group(0))
        return _ENV_RE.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_yaml_file(path: str) -> dict:
    """读取一个 YAML 文件，展开 ``${ENV}``，返回 dict（空文件返回 {}）。"""
    if yaml is None:
        raise ConfigError("缺少 pyyaml 依赖，请先 pip install pyyaml")
    if not os.path.isfile(path):
        raise ConfigError(f"配置文件不存在: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML 解析失败 {path}: {e}")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"配置文件根必须是字典: {path}")
    return _expand_env(raw)


# 基础 schema：仅校验框架运行必需的字段；模块自有字段由模块自行读取与校验
_SYSTEM_SCHEMA = {
    "serial": {
        "port": (str, True),
        "baudrate": (int, True),
        "timeout": ((int, float), False),
    },
}


def _validate_system(cfg: dict):
    """按 schema 校验 system 配置，失败抛 ConfigError。"""
    for section, fields in _SYSTEM_SCHEMA.items():
        if section not in cfg:
            raise ConfigError(f"system.yaml 缺少必填配置段: {section}")
        for key, (typ, required) in fields.items():
            if key not in cfg[section]:
                if required:
                    raise ConfigError(f"system.yaml 配置段 [{section}] 缺少必填项: {key}")
                continue
            val = cfg[section][key]
            types = typ if isinstance(typ, tuple) else (typ,)
            if not any(isinstance(val, t) for t in types):
                raise ConfigError(
                    f"配置项 [{section}].{key} 类型应为 {typ}，实际 {type(val).__name__}"
                )


def load_system(config_dir: str = None) -> dict:
    """加载并校验 system.yaml。"""
    config_dir = config_dir or CONFIG_DIR
    cfg = load_yaml_file(os.path.join(config_dir, "system.yaml"))
    _validate_system(cfg)
    return cfg


def _module_file(module_name: str) -> str:
    """模块名 -> 配置文件名。"""
    return _MODULE_FILE_MAP.get(module_name, module_name)


def load_module_config(module_name: str, config_dir: str = None) -> dict:
    """加载某模块的能力参数（modules/<file>.yaml），返回 dict。"""
    config_dir = config_dir or CONFIG_DIR
    path = os.path.join(config_dir, "modules", f"{_module_file(module_name)}.yaml")
    return load_yaml_file(path)


def load_scenario(name: str, config_dir: str = None) -> dict:
    """加载某测试场景（scenarios/<name>.yaml），返回含 ``scenario`` 键的 dict。"""
    config_dir = config_dir or CONFIG_DIR
    path = os.path.join(config_dir, "scenarios", f"{name}.yaml")
    cfg = load_yaml_file(path)
    if "scenario" not in cfg:
        raise ConfigError(f"场景 {name} 缺少 scenario 段")
    return cfg


def list_scenarios(config_dir: str = None) -> list:
    """列出所有可用场景名（按文件名）。"""
    config_dir = config_dir or CONFIG_DIR
    pat = os.path.join(config_dir, "scenarios", "*.yaml")
    names = []
    for p in sorted(glob.glob(pat)):
        base = os.path.basename(p)
        names.append(base[:-5])  # 去 .yaml
    return names


def apply_overrides(cfg: dict, overrides: dict) -> dict:
    """用 CLI 覆盖项合并进配置（覆盖项优先）。

    overrides 用扁平点号 key，如 ``{"serial.port": "/dev/ttyUSB1"}``。
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
