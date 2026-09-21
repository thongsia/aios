"""
DeepSeek Harness (dsh) adapter.

Wraps `dsh --profile headless "PROMPT"` for one-shot Q&A.
"""

import os
import shutil
from pathlib import Path

from .base import HarnessAdapter


class DshAdapter(HarnessAdapter):
    NAME = "dsh"
    BINARY = "dsh"

    def prepare_isolated_home(self, home: Path) -> None:
        """Copy DSH config into isolated home."""
        src = Path.home() / ".dsh"
        dst = home / ".dsh"
        if src.exists():
            shutil.copytree(src, dst)

    def build_command(self, prompt: str) -> list[str]:
        return ["dsh", "--profile", "headless", prompt]

    def build_env(self, original_env: dict) -> dict:
        env = original_env.copy()
        # Read-only sandbox
        env["DSH_PERMISSION_MODE"] = "read-only"
        # Point dsh at ~/.dsh where settings.yaml configures local llama.cpp
        env.setdefault("DSH_HOME", str(Path.home() / ".dsh"))
        # settings.yaml uses apiKeyEnv: DUMMY_API_KEY
        env.setdefault("DUMMY_API_KEY", "dummy")
        return env
