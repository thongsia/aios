"""
Opencode harness adapter.

Wraps `opencode run 'PROMPT'` with format=json for structured output.
"""

import os
import shutil
from pathlib import Path
from .base import HarnessAdapter


class OpencodeAdapter(HarnessAdapter):
    NAME = "opencode"
    BINARY = "opencode"

    def build_command(self, prompt: str) -> list[str]:
        return ["opencode", "run", "--format", "json", prompt]

    def build_env(self, original_env: dict) -> dict:
        env = original_env.copy()
        # Pass through API keys that Opencode may use
        for key in [
            "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
            "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY",
        ]:
            if key in original_env:
                env[key] = original_env[key]
        return env

    def prepare_isolated_home(self, isolated_home: str, original_env: dict) -> None:
        """Copy opencode config into the isolated HOME.

        Copies both ~/.opencode/ (legacy) and ~/.config/opencode/ (v1.18+).
        """
        import shutil
        src_home = Path(original_env.get("HOME", "~")).expanduser()
        isolated = Path(isolated_home)

        # Legacy: ~/.opencode/
        src_legacy = src_home / ".opencode"
        if src_legacy.is_dir():
            dst_legacy = isolated / ".opencode"
            dst_legacy.mkdir(parents=True, exist_ok=True)
            for item in src_legacy.iterdir():
                if item.name not in ("node_modules", "bin", "package-lock.json"):
                    if item.is_file():
                        shutil.copy2(item, dst_legacy / item.name)

        # Modern (v1.18+): ~/.config/opencode/
        src_config = src_home / ".config" / "opencode"
        if src_config.is_dir():
            dst_config = isolated / ".config" / "opencode"
            dst_config.mkdir(parents=True, exist_ok=True)
            for item in src_config.iterdir():
                if item.is_file():
                    shutil.copy2(item, dst_config / item.name)
