#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path

# ============================================================
# 配置
# ============================================================

# 要扫描的目录
SOURCE_DIR = Path(".")

# 最终输出文件
OUTPUT_FILE = Path("all_source.txt")

# 忽略的目录
IGNORE_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "node_modules",
}

# 忽略的文件
IGNORE_FILES = {
    OUTPUT_FILE.name,
}

# 常见二进制文件后缀
BINARY_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
    ".mp4", ".avi", ".mkv", ".mov", ".flv", ".ts",
    ".mp3", ".wav", ".aac",
    ".zip", ".tar", ".gz", ".7z", ".rar",
    ".pdf",
    ".exe", ".dll", ".so", ".a", ".o",
    ".pyc",
    ".bin", ".dat",
}


# ============================================================
# 判断是否忽略
# ============================================================

def should_ignore(path: Path) -> bool:
    """判断文件或目录是否需要忽略。"""

    # 路径中任意一级目录属于忽略目录
    if any(part in IGNORE_DIRS for part in path.parts):
        return True

    # 忽略指定文件
    if path.name in IGNORE_FILES:
        return True

    return False


# ============================================================
# 获取所有文件
# ============================================================

def collect_files(root: Path):
    files = []

    for path in root.rglob("*"):

        relative = path.relative_to(root)

        if should_ignore(relative):
            continue

        if path.is_file():
            files.append(path)

    return sorted(files, key=lambda p: str(p.relative_to(root)))


# ============================================================
# 生成目录树
# ============================================================

def generate_tree(root: Path) -> str:
    lines = [f"{root.name}/"]

    def walk(directory: Path, prefix=""):

        entries = []

        for entry in directory.iterdir():

            relative = entry.relative_to(root)

            if should_ignore(relative):
                continue

            entries.append(entry)

        # 目录优先，然后文件
        entries.sort(
            key=lambda p: (
                not p.is_dir(),
                p.name.lower()
            )
        )

        for index, entry in enumerate(entries):

            is_last = index == len(entries) - 1

            connector = "└── " if is_last else "├── "

            lines.append(
                prefix + connector + entry.name + ("/" if entry.is_dir() else "")
            )

            if entry.is_dir():

                extension = "    " if is_last else "│   "

                walk(
                    entry,
                    prefix + extension
                )

    walk(root)

    return "\n".join(lines)


# ============================================================
# 判断是否二进制文件
# ============================================================

def is_binary_file(path: Path) -> bool:

    if path.suffix.lower() in BINARY_SUFFIXES:
        return True

    try:
        with open(path, "rb") as f:
            chunk = f.read(4096)

        # 文件中存在 NULL 字节，大概率是二进制文件
        if b"\x00" in chunk:
            return True

    except Exception:
        return True

    return False


# ============================================================
# 读取文本文件
# ============================================================

def read_text_file(path: Path):

    encodings = [
        "utf-8",
        "utf-8-sig",
        "gb18030",
        "gbk",
        "latin-1",
    ]

    for encoding in encodings:

        try:
            return path.read_text(encoding=encoding)

        except UnicodeDecodeError:
            continue

        except Exception as e:
            return f"[读取失败: {e}]"

    return "[无法识别文件编码]"


# ============================================================
# 主程序
# ============================================================

def main():

    root = SOURCE_DIR.resolve()

    if not root.exists():
        print(f"目录不存在: {root}")
        return

    if not root.is_dir():
        print(f"不是目录: {root}")
        return

    files = collect_files(root)

    print(f"扫描目录: {root}")
    print(f"发现文件: {len(files)}")

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8"
    ) as out:

        # ----------------------------------------------------
        # 1. 输出目录结构
        # ----------------------------------------------------

        out.write("=" * 100)
        out.write("\nDIRECTORY TREE\n")
        out.write("=" * 100)
        out.write("\n\n")

        out.write(generate_tree(root))

        out.write("\n\n")

        # ----------------------------------------------------
        # 2. 输出所有文件内容
        # ----------------------------------------------------

        out.write("=" * 100)
        out.write("\nFILE CONTENTS\n")
        out.write("=" * 100)
        out.write("\n\n")

        for index, path in enumerate(files, 1):

            relative_path = path.relative_to(root)

            out.write("\n")
            out.write("=" * 100)
            out.write("\n")

            out.write(
                f"FILE [{index}/{len(files)}]: {relative_path}\n"
            )

            out.write("=" * 100)
            out.write("\n\n")

            if is_binary_file(path):

                out.write(
                    "[Binary file skipped]\n"
                )

                continue

            content = read_text_file(path)

            out.write(content)

            # 确保文件末尾换行
            if not content.endswith("\n"):
                out.write("\n")

    print()
    print("完成。")
    print(f"输出文件: {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()