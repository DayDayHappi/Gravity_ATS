"""Keep non-GUI engine modules importable on the documented Python 3.8 floor."""
from __future__ import annotations

import ast
from pathlib import Path


ENGINE_ROOTS = (
    Path("ATS/application"),
    Path("ATS/core"),
    Path("ATS/drivers"),
    Path("ATS/modules"),
    Path("ATS/platform"),
)
_BUILTIN_GENERICS = {"list", "dict", "tuple", "set", "frozenset", "type"}


def _has_future_annotations(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )


def _annotations(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            yield node.annotation
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                if argument.annotation is not None:
                    yield argument.annotation
            if node.args.vararg and node.args.vararg.annotation is not None:
                yield node.args.vararg.annotation
            if node.args.kwarg and node.args.kwarg.annotation is not None:
                yield node.args.kwarg.annotation
            if node.returns is not None:
                yield node.returns


def test_engine_annotations_are_safe_on_python38():
    violations = []
    for root in ENGINE_ROOTS:
        for source in root.rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            if _has_future_annotations(tree):
                continue
            for annotation in _annotations(tree):
                for node in ast.walk(annotation):
                    if (
                        isinstance(node, ast.Subscript)
                        and isinstance(node.value, ast.Name)
                        and node.value.id in _BUILTIN_GENERICS
                    ):
                        violations.append(f"{source}: builtin generic {node.value.id}[...] without future annotations")
                    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
                        violations.append(f"{source}: PEP 604 union without future annotations")
    assert violations == []
