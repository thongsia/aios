"""
Qwen Code harness adapter.

Wraps `qwen -p "PROMPT" --approval-mode plan` for analysis-only mode.

Endpoint configuration is per-machine — the repo carries no hardcoded
default. The adapter resolves, in order:

  AIOS_QWEN_BASE_URL   OpenAI-compatible base URL (e.g. a local vLLM host)
  AIOS_QWEN_MODEL      model id served by that endpoint
  AIOS_QWEN_API_KEY    optional; defaults to "dummy" (no-auth local endpoints)

Resolution: process env first, then ~/.hermes/.env (same convention as the
kakis scripts' AIOS_OPENSEARCH). If AIOS_QWEN_BASE_URL resolves to nothing,
no OPENAI_* vars are injected and qwen falls back to its own config
(~/.config/qwen). Values already present in the environment always win
(setdefault semantics).
"""

import os
import shutil
from pathlib import Path

from .base import HarnessAdapter


def _aios_env_file() -> Path:
    """Locate ~/.hermes/.env via the real user home.

    NOTE: use Path.home() (pwd/realuid), NOT os.path.expanduser — by the
    time build_env runs, the harness env's HOME has been overridden to the
    isolated workspace dir, so expanduser would resolve to the wrong place.
    """
    return Path.home() / ".hermes" / ".env"


def _resolve(name: str, env_file: Path | None = None) -> str | None:
    """Value of `name` from process env, else from the AIOS env file, else None."""
    v = os.environ.get(name)
    if v and v.strip():
        return v.strip()
    env_file = env_file or _aios_env_file()
    try:
        if env_file.is_file():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, val = line.partition("=")
                if k.strip() == name:
                    val = val.strip().strip('"').strip("'")
                    if val:
                        return val
    except OSError:
        pass
    return None


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
        # Endpoint is per-machine: AIOS_QWEN_* from process env or
        # ~/.hermes/.env. No hardcoded default in the repo.
        base_url = _resolve("AIOS_QWEN_BASE_URL")
        if not base_url:
            # Not configured here: leave OPENAI_* untouched so qwen uses
            # its own config (~/.config/qwen) if it has one.
            return env
        # Only override if the user hasn't already set these
        env.setdefault("OPENAI_API_KEY", _resolve("AIOS_QWEN_API_KEY") or "dummy")
        env.setdefault("OPENAI_BASE_URL", base_url)
        model = _resolve("AIOS_QWEN_MODEL")
        if model:
            env.setdefault("OPENAI_MODEL", model)
        return env
