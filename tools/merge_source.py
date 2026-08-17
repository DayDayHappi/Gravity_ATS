#!/usr/bin/env python3

import sys
from pathlib import Path
from typing import List, Tuple


# 默认忽略的目录
IGNORE_DIRS = {
    ".git",
    ".svn",
    "__pycache__",
    ".idea",
    ".vscode",
}

# 默认忽略的文件
IGNORE_FILES = {
    ".DS_Store",
}


def is_binary_file(file_path: Path) -> bool:
    """
    简单判断文件是否为二进制文件。
    """
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(4096)

        # 包含 \0，一般认为是二进制文件
        return b"\x00" in chunk

    except Exception:
        return True


def build_tree(
    root: Path,
    output_file: Path
) -> Tuple[List[str], List[Path]]:
    """
    生成目录树，同时返回所有需要读取的文件。
    """

    lines = []
    files = []

    root = root.resolve()
    output_file = output_file.resolve()

    lines.append(root.name + "/")

    def walk(directory: Path, prefix: str) -> None:

        try:
            entries = []

            for entry in directory.iterdir():

                # 忽略指定目录
                if entry.name in IGNORE_DIRS:
                    continue

                # 忽略指定文件
                if entry.name in IGNORE_FILES:
                    continue

                # 避免把输出文件自己再次读取进去
                try:
                    if entry.resolve() == output_file:
                        continue
                except Exception:
                    pass

                entries.append(entry)

            # 目录优先，然后按名字排序
            entries.sort(
                key=lambda x: (
                    not x.is_dir(),
                    x.name.lower()
                )
            )

        except PermissionError:
            lines.append(prefix + "└── [Permission Denied]")
            return

        except Exception as e:
            lines.append(prefix + "└── [Error: {}]".format(e))
            return

        for index, entry in enumerate(entries):

            is_last = index == len(entries) - 1

            if is_last:
                connector = "└── "
                child_prefix = "    "
            else:
                connector = "├── "
                child_prefix = "│   "

            if entry.is_dir():

                lines.append(
                    prefix
                    + connector
                    + entry.name
                    + "/"
                )

                walk(
                    entry,
                    prefix + child_prefix
                )

            else:

                lines.append(
                    prefix
                    + connector
                    + entry.name
                )

                files.append(entry)

    walk(root, "")

    return lines, files


def read_text_file(file_path: Path) -> str:
    """
    尝试使用多种编码读取文本文件。
    """

    encodings = [
        "utf-8",
        "utf-8-sig",
        "gb18030",
        "gbk",
        "latin-1",
    ]

    for encoding in encodings:

        try:

            with open(
                file_path,
                "r",
                encoding=encoding
            ) as f:

                return f.read()

        except UnicodeDecodeError:
            continue

        except Exception as e:
            return "[读取失败: {}]".format(e)

    return "[无法识别文件编码]"


def merge_directory(
    root_dir: str,
    output_path: str
) -> None:

    root = Path(root_dir)
    output_file = Path(output_path)

    # 检查目录是否存在
    if not root.exists():

        print(
            "错误：目录不存在：{}".format(
                root
            )
        )

        sys.exit(1)

    # 检查是不是目录
    if not root.is_dir():

        print(
            "错误：不是目录：{}".format(
                root
            )
        )

        sys.exit(1)

    tree_lines, files = build_tree(
        root,
        output_file
    )

    # 如果输出目录不存在，就创建
    output_parent = output_file.parent

    if str(output_parent) != ".":
        output_parent.mkdir(
            parents=True,
            exist_ok=True
        )

    with open(
        output_file,
        "w",
        encoding="utf-8"
    ) as out:

        # ======================================================
        # 目录树
        # ======================================================

        out.write("=" * 80 + "\n")
        out.write("DIRECTORY TREE\n")
        out.write("=" * 80 + "\n\n")

        out.write(
            "\n".join(tree_lines)
        )

        out.write("\n\n")

        # ======================================================
        # 文件内容
        # ======================================================

        out.write("=" * 80 + "\n")
        out.write("FILE CONTENTS\n")
        out.write("=" * 80 + "\n\n")

        for file_path in files:

            try:
                relative_path = file_path.relative_to(root)
            except ValueError:
                relative_path = file_path

            out.write("\n")
            out.write("=" * 80 + "\n")
            out.write(
                "FILE: {}\n".format(
                    relative_path
                )
            )
            out.write("=" * 80 + "\n\n")

            # 二进制文件跳过
            if is_binary_file(file_path):

                out.write(
                    "[Binary file skipped]\n"
                )

                continue

            content = read_text_file(
                file_path
            )

            out.write(content)

            # 保证不同文件之间有换行
            if not content.endswith("\n"):
                out.write("\n")

    print("")
    print("完成！")
    print(
        "扫描目录: {}".format(
            root.resolve()
        )
    )
    print(
        "文件数量: {}".format(
            len(files)
        )
    )
    print(
        "输出文件: {}".format(
            output_file.resolve()
        )
    )


def main() -> None:

    if len(sys.argv) != 3:

        print("")
        print("用法:")
        print(
            "  python3 {} <目录> <输出文件>".format(
                sys.argv[0]
            )
        )

        print("")
        print("例如:")
        print(
            "  python3 {} ../src all_source.txt".format(
                sys.argv[0]
            )
        )

        print("")

        sys.exit(1)

    root_dir = sys.argv[1]
    output_path = sys.argv[2]

    merge_directory(
        root_dir,
        output_path
    )


if __name__ == "__main__":
    main()
