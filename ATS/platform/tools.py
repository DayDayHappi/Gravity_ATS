"""FFmpeg 套件定位：工程相对路径、平台区分和可运行性验证。

默认/历史 tools/ffmpeg/<name>：平台内置目录 → PATH。
用户指定的其它路径：严格使用，不因路径写错而悄悄换用系统版本。
不修改 PATH/cwd，不下载二进制，不包含业务判据。
"""
import os
import shutil
from pathlib import Path

from .processes import run_capture

IS_WINDOWS = os.name == "nt"
_TOOL_NAMES = {"ffmpeg", "ffprobe", "ffplay"}


class ToolError(RuntimeError):
    """未找到可运行的当前平台工具。"""


def project_root():
    return Path(__file__).resolve().parents[2]


def _usable_file(path):
    if not path.is_file() or path.suffix.lower() in {".bat", ".cmd", ".ps1"}:
        return False
    if IS_WINDOWS:
        if path.suffix.lower() != ".exe":
            return False
        try:
            with path.open("rb") as f:
                return f.read(2) == b"MZ"
        except OSError:
            return False
    return os.access(str(path), os.X_OK) and path.suffix.lower() != ".exe"


def resolve_tool(name, preferred=None, root=None):
    """返回经 `-version` 验证的绝对路径；失败抛 ToolError。"""
    if name not in _TOOL_NAMES:
        raise ToolError(f"未支持的工具名: {name}")
    root = Path(root) if root is not None else project_root()
    root = root.resolve()
    pref = os.path.expanduser(os.path.expandvars(str(preferred or ""))).strip()
    normalized = pref.replace("\\", "/")
    automatic = normalized in {"", "auto", name, name + ".exe",
                               "tools/ffmpeg/" + name,
                               "tools/ffmpeg/" + name + ".exe"}
    candidates = []
    if automatic:
        if IS_WINDOWS:
            candidates.extend([root / "tools/ffmpeg/windows" / (name + ".exe"),
                               root / "tools/ffmpeg" / (name + ".exe")])
        else:
            candidates.extend([root / "tools/ffmpeg" / name,
                               root / "tools/ffmpeg/linux" / name])
        found = shutil.which(name + ".exe" if IS_WINDOWS else name)
        if found:
            candidates.append(Path(found))
    else:
        explicit = Path(pref)
        candidates.append(explicit if explicit.is_absolute() else root / explicit)
    failures = []
    seen = set()
    for path in candidates:
        path = path.resolve()
        if str(path) in seen:
            continue
        seen.add(str(path))
        if not _usable_file(path):
            failures.append(f"{path}: 不存在或不可执行（平台/权限/文件类型不匹配）")
            continue
        try:
            check = run_capture([str(path), "-version"], timeout=10.0)
            text = (check.stdout or "") + (check.stderr or "")
            if check.returncode == 0 and f"{name} version" in text.lower():
                return str(path)
            failures.append(f"{path}: -version 校验失败: {text.strip()[:200]}")
        except (OSError, RuntimeError, ValueError) as exc:
            failures.append(f"{path}: 无法运行: {exc}")
        except TimeoutError as exc:
            failures.append(f"{path}: -version 超时: {exc}")
        except Exception as exc:
            # subprocess.TimeoutExpired 等：不给不存在/卡住的工具假通过。
            failures.append(f"{path}: -version 校验失败: {exc}")
    where = "Windows .exe" if IS_WINDOWS else "Linux/POSIX 可执行文件"
    raise ToolError(f"未找到可运行的 {name}（需要 {where}）。\n" + "\n".join(failures))
