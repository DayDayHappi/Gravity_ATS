#!/usr/bin/env python3

import sys
import argparse
from pathlib import Path
from typing import List, Tuple, Set


# ============================================================
# 默认忽略的目录
# ============================================================
DEFAULT_IGNORE_DIRS = {
    ".git",
    ".svn",
    "__pycache__",
    ".idea",
    ".vscode",
}


# ============================================================
# 默认忽略的文件
# ============================================================
DEFAULT_IGNORE_FILES = {
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


def should_ignore_directory(
    directory: Path,
    root: Path,
    ignore_dirs: Set[str]
) -> bool:
    """
    判断目录是否应该被忽略。

    支持两种方式：

    1. 只写目录名：
       --ignore-dir build

       会忽略任意层级名为 build 的目录。

    2. 写相对路径：
       --ignore-dir src/third_party

       只忽略指定路径。
    """

    try:
        relative_path = directory.relative_to(root)
    except ValueError:
        return False

    relative_str = str(relative_path)

    # 转成统一的 /
    relative_str = relative_str.replace("\\", "/")

    for ignore_item in ignore_dirs:

        ignore_item = ignore_item.replace("\\", "/")
        ignore_item = ignore_item.rstrip("/")

        # ----------------------------------------------------
        # 情况 1：
        # 用户只写了目录名，例如：
        #
        # build
        #
        # 那么所有叫 build 的目录都忽略
        # ----------------------------------------------------
        if "/" not in ignore_item:

            if directory.name == ignore_item:
                return True

        # ----------------------------------------------------
        # 情况 2：
        # 用户写了相对路径，例如：
        #
        # src/third_party
        #
        # 只忽略指定路径
        # ----------------------------------------------------
        else:

            if relative_str == ignore_item:
                return True

    return False


def build_tree(
    root: Path,
    output_file: Path,
    ignore_dirs: Set[str],
    ignore_files: Set[str]
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

                # ==================================================
                # 目录
                # ==================================================
                if entry.is_dir():

                    if should_ignore_directory(
                        entry,
                        root,
                        ignore_dirs
                    ):
                        continue

                # ==================================================
                # 文件
                # ==================================================
                else:

                    if entry.name in ignore_files:
                        continue

                # ==================================================
                # 避免把输出文件自己读进去
                # ==================================================
                try:

                    if entry.resolve() == output_file:
                        continue

                except Exception:
                    pass

                entries.append(entry)

            # ======================================================
            # 排序
            #
            # 目录优先
            # 文件其次
            # 同类按名字排序
            # ======================================================
            entries.sort(
                key=lambda x: (
                    not x.is_dir(),
                    x.name.lower()
                )
            )

        except PermissionError:

            lines.append(
                prefix + "└── [Permission Denied]"
            )

            return

        except Exception as e:

            lines.append(
                prefix
                + "└── [Error: {}]".format(e)
            )

            return

        for index, entry in enumerate(entries):

            is_last = (
                index == len(entries) - 1
            )

            if is_last:

                connector = "└── "
                child_prefix = "    "

            else:

                connector = "├── "
                child_prefix = "│   "

            # ======================================================
            # 目录
            # ======================================================
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

            # ======================================================
            # 文件
            # ======================================================
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

            return (
                "[读取失败: {}]".format(e)
            )

    return "[无法识别文件编码]"


def merge_directory(
    root_dir: str,
    output_path: str,
    user_ignore_dirs: List[str]
) -> None:

    root = Path(root_dir)
    output_file = Path(output_path)

    # ============================================================
    # 检查目录
    # ============================================================

    if not root.exists():

        print(
            "错误：目录不存在：{}".format(
                root
            )
        )

        sys.exit(1)

    if not root.is_dir():

        print(
            "错误：不是目录：{}".format(
                root
            )
        )

        sys.exit(1)

    root = root.resolve()

    # ============================================================
    # 合并：
    #
    # 默认忽略目录
    # +
    # 用户指定忽略目录
    # ============================================================

    ignore_dirs = set(
        DEFAULT_IGNORE_DIRS
    )

    for directory in user_ignore_dirs:
        ignore_dirs.add(directory)

    ignore_files = set(
        DEFAULT_IGNORE_FILES
    )

    # ============================================================
    # 打印本次扫描配置
    # ============================================================

    print("")
    print("=" * 60)
    print("扫描配置")
    print("=" * 60)

    print(
        "扫描目录：{}".format(root)
    )

    print("")
    print("忽略目录：")

    for directory in sorted(ignore_dirs):

        print(
            "  - {}".format(directory)
        )

    print("")

    # ============================================================
    # 生成目录树
    # ============================================================

    tree_lines, files = build_tree(
        root,
        output_file,
        ignore_dirs,
        ignore_files
    )

    # ============================================================
    # 创建输出目录
    # ============================================================

    output_parent = output_file.parent

    if str(output_parent) != ".":

        output_parent.mkdir(
            parents=True,
            exist_ok=True
        )

    # ============================================================
    # 写文件
    # ============================================================

    with open(
        output_file,
        "w",
        encoding="utf-8"
    ) as out:

        # ========================================================
        # 扫描信息
        # ========================================================

        out.write(
            "=" * 80 + "\n"
        )

        out.write(
            "SCAN INFORMATION\n"
        )

        out.write(
            "=" * 80 + "\n\n"
        )

        out.write(
            "ROOT DIRECTORY:\n"
        )

        out.write(
            "{}\n\n".format(root)
        )

        out.write(
            "IGNORED DIRECTORIES:\n"
        )

        for directory in sorted(ignore_dirs):

            out.write(
                "  - {}\n".format(
                    directory
                )
            )

        out.write("\n")

        # ========================================================
        # 目录树
        # ========================================================

        out.write(
            "=" * 80 + "\n"
        )

        out.write(
            "DIRECTORY TREE\n"
        )

        out.write(
            "=" * 80 + "\n\n"
        )

        out.write(
            "\n".join(tree_lines)
        )

        out.write(
            "\n\n"
        )

        # ========================================================
        # 文件内容
        # ========================================================

        out.write(
            "=" * 80 + "\n"
        )

        out.write(
            "FILE CONTENTS\n"
        )

        out.write(
            "=" * 80 + "\n\n"
        )

        for file_path in files:

            try:

                relative_path = (
                    file_path.relative_to(root)
                )

            except ValueError:

                relative_path = file_path

            out.write("\n")

            out.write(
                "=" * 80 + "\n"
            )

            out.write(
                "FILE: {}\n".format(
                    relative_path
                )
            )

            out.write(
                "=" * 80 + "\n\n"
            )

            # ====================================================
            # 二进制文件跳过
            # ====================================================

            if is_binary_file(file_path):

                out.write(
                    "[Binary file skipped]\n"
                )

                continue

            # ====================================================
            # 文本文件读取
            # ====================================================

            content = read_text_file(
                file_path
            )

            out.write(content)

            # 不同文件之间保证有换行
            if not content.endswith("\n"):

                out.write("\n")

    # ============================================================
    # 最终结果
    # ============================================================

    print("")
    print("=" * 60)
    print("完成")
    print("=" * 60)

    print(
        "扫描目录：{}".format(
            root
        )
    )

    print(
        "读取文件数量：{}".format(
            len(files)
        )
    )

    print(
        "输出文件：{}".format(
            output_file.resolve()
        )
    )

    print("")


def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "递归读取指定目录，"
            "生成目录树并合并所有文本文件内容"
        )
    )

    # ============================================================
    # 必选参数
    # ============================================================

    parser.add_argument(
        "root_dir",
        help="需要扫描的目录"
    )

    parser.add_argument(
        "output_file",
        help="生成的输出文件"
    )

    # ============================================================
    # 可选参数
    # ============================================================

    parser.add_argument(
        "--ignore-dir",
        action="append",
        default=[],
        help=(
            "忽略指定目录。"
            "可以重复使用该参数。"
            "例如："
            "--ignore-dir build "
            "--ignore-dir output"
        )
    )

    args = parser.parse_args()

    merge_directory(
        args.root_dir,
        args.output_file,
        args.ignore_dir
    )


if __name__ == "__main__":
    main()