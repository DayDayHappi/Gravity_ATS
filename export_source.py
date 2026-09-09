from pathlib import Path
from datetime import datetime

# ============================================================
# 配置
# ============================================================

ROOT_DIR = Path(__file__).resolve().parent

SCAN_DIRS = [
    "ATS",
    "docs",
]

OUTPUT_FILE = ROOT_DIR / "all_source.txt"

# 不扫描的目录
EXCLUDE_DIRS = {
    "__pycache__",
    ".git",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

# 不扫描的文件
EXCLUDE_FILES = {
    OUTPUT_FILE.name,
}

# 明显属于二进制/不适合展开到源码快照中的文件
BINARY_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".exe",
    ".bin",
    ".obj",
    ".o",
    ".a",
    ".lib",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".pdf",
    ".zip",
    ".7z",
    ".rar",
    ".tar",
    ".gz",
    ".mp3",
    ".wav",
    ".mp4",
    ".avi",
    ".mov",
}


# ============================================================
# 工具函数
# ============================================================

def should_skip(path: Path) -> bool:
    """判断文件/目录是否应该跳过。"""

    if path.name in EXCLUDE_FILES:
        return True

    if any(part in EXCLUDE_DIRS for part in path.parts):
        return True

    if path.is_file() and path.suffix.lower() in BINARY_SUFFIXES:
        return True

    return False


def is_probably_binary(path: Path) -> bool:
    """
    进一步检测无后缀或未知后缀文件是否为二进制文件。
    检查前 4096 字节中是否存在 NULL 字节。
    """
    try:
        with path.open("rb") as f:
            chunk = f.read(4096)
        return b"\x00" in chunk
    except OSError:
        return True


def read_text_file(path: Path) -> str:
    """
    尝试用常见编码读取文件。
    """
    encodings = [
        "utf-8",
        "utf-8-sig",
        "gb18030",
        "gbk",
    ]

    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue

    # 最后的兜底策略，避免整个扫描因为一个文件失败
    return path.read_text(encoding="utf-8", errors="replace")


def get_scan_roots():
    """获取实际存在的扫描目录。"""
    roots = []

    for dirname in SCAN_DIRS:
        path = ROOT_DIR / dirname

        if path.exists() and path.is_dir():
            roots.append(path)
        else:
            print(f"[WARN] 目录不存在，跳过: {path}")

    return roots


def collect_files(scan_roots):
    """收集所有需要导出的文本文件。"""
    files = []

    for scan_root in scan_roots:
        for path in scan_root.rglob("*"):
            if not path.is_file():
                continue

            if should_skip(path):
                continue

            if is_probably_binary(path):
                continue

            files.append(path)

    return sorted(
        files,
        key=lambda p: str(p.relative_to(ROOT_DIR)).lower()
    )


# ============================================================
# 目录树
# ============================================================

def build_tree(scan_roots):
    """生成 ATS 和 docs 的目录树。"""

    lines = [ROOT_DIR.name + "/"]

    roots = sorted(scan_roots, key=lambda p: p.name.lower())

    for root_index, scan_root in enumerate(roots):
        is_last_root = root_index == len(roots) - 1

        root_prefix = "└── " if is_last_root else "├── "
        lines.append(f"{root_prefix}{scan_root.name}/")

        child_prefix = "    " if is_last_root else "│   "

        _build_tree_recursive(
            scan_root,
            child_prefix,
            lines,
        )

    return "\n".join(lines)


def _build_tree_recursive(directory: Path, prefix: str, lines: list[str]):
    """递归生成单个目录下的目录树。"""

    entries = []

    try:
        for entry in directory.iterdir():
            if should_skip(entry):
                continue

            # 二进制文件仍然不进入目录树
            if entry.is_file():
                if entry.suffix.lower() in BINARY_SUFFIXES:
                    continue

                if is_probably_binary(entry):
                    continue

            entries.append(entry)

    except PermissionError:
        lines.append(prefix + "└── [Permission Denied]")
        return

    entries.sort(
        key=lambda p: (
            not p.is_dir(),
            p.name.lower(),
        )
    )

    for index, entry in enumerate(entries):
        is_last = index == len(entries) - 1

        connector = "└── " if is_last else "├── "

        if entry.is_dir():
            lines.append(
                f"{prefix}{connector}{entry.name}/"
            )

            next_prefix = prefix + (
                "    " if is_last else "│   "
            )

            _build_tree_recursive(
                entry,
                next_prefix,
                lines,
            )

        else:
            lines.append(
                f"{prefix}{connector}{entry.name}"
            )


# ============================================================
# 输出
# ============================================================

def export():
    scan_roots = get_scan_roots()

    if not scan_roots:
        print("[ERROR] 没有找到 ATS 或 docs 目录。")
        return

    files = collect_files(scan_roots)
    tree = build_tree(scan_roots)

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as output:

        # ----------------------------------------------------
        # 文件头
        # ----------------------------------------------------

        output.write("=" * 80 + "\n")
        output.write("Gravity ATS Source Snapshot\n")
        output.write("=" * 80 + "\n\n")

        output.write(
            f"Generated At : "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )

        output.write(
            f"Project Root : {ROOT_DIR}\n"
        )

        output.write(
            f"Scan Dirs    : {', '.join(SCAN_DIRS)}\n"
        )

        output.write(
            f"Total Files  : {len(files)}\n"
        )

        output.write("\n")

        # ----------------------------------------------------
        # 目录树
        # ----------------------------------------------------

        output.write("=" * 80 + "\n")
        output.write("DIRECTORY TREE\n")
        output.write("=" * 80 + "\n\n")

        output.write(tree)
        output.write("\n\n")

        # ----------------------------------------------------
        # 文件正文
        # ----------------------------------------------------

        output.write("=" * 80 + "\n")
        output.write("FILE CONTENTS\n")
        output.write("=" * 80 + "\n\n")

        for index, path in enumerate(files, start=1):

            relative_path = path.relative_to(ROOT_DIR)

            output.write("\n")
            output.write("#" * 80 + "\n")
            output.write(
                f"# FILE {index}/{len(files)}: "
                f"{relative_path.as_posix()}\n"
            )
            output.write("#" * 80 + "\n\n")

            try:
                content = read_text_file(path)

                output.write(content)

                if content and not content.endswith("\n"):
                    output.write("\n")

            except Exception as exc:
                output.write(
                    f"[ERROR] Failed to read file: {exc}\n"
                )

            output.write("\n")

    print("=" * 60)
    print("扫描完成")
    print(f"工程目录 : {ROOT_DIR}")
    print(f"扫描目录 : {', '.join(SCAN_DIRS)}")
    print(f"文件数量 : {len(files)}")
    print(f"输出文件 : {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    export()