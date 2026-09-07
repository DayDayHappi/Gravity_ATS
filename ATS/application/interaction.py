"""Human-interaction contracts independent of stdin and GUI toolkits."""
from __future__ import annotations

import getpass
from typing import Sequence, TypeVar

T = TypeVar("T")


class InteractionProvider:
    """Minimal provider used by application/prepare flows that need a human choice."""

    def confirm(self, prompt: str, default: bool = True) -> bool:
        raise NotImplementedError

    def choose(self, prompt: str, options: Sequence[T], default_index: int = 0) -> T:
        raise NotImplementedError

    def ask_text(self, prompt: str, default: str = "", secret: bool = False) -> str:
        raise NotImplementedError


class NonInteractiveInteractionProvider(InteractionProvider):
    """Deterministic provider suitable for tests, services, and unattended runs."""

    def confirm(self, prompt: str, default: bool = True) -> bool:
        return bool(default)

    def choose(self, prompt: str, options: Sequence[T], default_index: int = 0) -> T:
        if not options:
            raise ValueError("options must not be empty")
        index = min(max(int(default_index), 0), len(options) - 1)
        return options[index]

    def ask_text(self, prompt: str, default: str = "", secret: bool = False) -> str:
        return default


class CliInteractionProvider(InteractionProvider):
    """Terminal implementation used exclusively by the CLI presentation."""

    def confirm(self, prompt: str, default: bool = True) -> bool:
        suffix = " [Y/n]: " if default else " [y/N]: "
        answer = input(prompt + suffix).strip().lower()
        if not answer:
            return default
        return answer in ("y", "yes", "1", "true")

    def choose(self, prompt: str, options: Sequence[T], default_index: int = 0) -> T:
        if not options:
            raise ValueError("options must not be empty")
        print(prompt)
        for index, option in enumerate(options):
            print(f"  [{index}] {option}")
        answer = input(f"选择序号（默认 {default_index}）: ").strip()
        try:
            index = int(answer) if answer else default_index
            return options[index]
        except (ValueError, IndexError):
            return options[min(max(default_index, 0), len(options) - 1)]

    def ask_text(self, prompt: str, default: str = "", secret: bool = False) -> str:
        suffix = f"（默认 {default}）" if default and not secret else ""
        reader = getpass.getpass if secret else input
        answer = reader(f"{prompt}{suffix}: ").strip()
        return answer or default
