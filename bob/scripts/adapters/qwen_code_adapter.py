"""
Qwen Code harness adapter.

Wraps `qwen -p "PROMPT" --approval-mode plan` for analysis-only mode.
"""

import os
import shutil
from pathlib import Path

from .base import HarnessAdapter


class QwenCodeAdapter(HarnessAdapter):
    NAME = "qwen"
    BINARY = "qwen"

    def prepare_isolated_home(self, home: Path) -> None:
        """Copy Qwen Code config into isolated home."""
        src = Path.home() / ".config" / "qwen"
        dst = home / ".config" / "qwen"
        if src.exists():
            shutil.copytree(src, dst)

    def build_command(self, prompt: str) -> list[str]:
        # --bare skips hooks/extensions/skills that hang in non-interactive mode
        # --output-format text for machine-parseable output
        return ["qwen", "--bare", "-p", prompt, "--output-format", "text"]

    def build_fallback_command(self, prompt: str) -> list[str]:
        return ["qwen", "--bare", "-p", prompt]

    def build_env(self, original_env: dict) -> dict:
        env = original_env.copy()
        # Point Qwen Code at the local llama.cpp OpenAI-compatible endpoint
        # Only override if the user hasn't already set these
        env.setdefault("OPENAI_API_KEY", "dummy")
        env.setdefault("OPENAI_BASE_URL", "http://llama.local:11435/v1")
        env.setdefault("OPENAI_MODEL", "Qwen3.8-27B")
        return env
