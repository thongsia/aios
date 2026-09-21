"""
Hermes harness adapter.

Wraps `hermes -z 'PROMPT'` with recursion guard:
  HERMES_PROFILE=bob-worker + --ignore-rules
"""

from pathlib import Path
from .base import HarnessAdapter


class HermesAdapter(HarnessAdapter):
    NAME = "hermes"
    BINARY = "hermes"

    def build_command(self, prompt: str) -> list[str]:
        # Use `hermes chat` with -q for single-turn non-interactive execution
        # --quiet suppresses banners/spinners
        # --ignore-rules prevents loading skills, AGENTS.md, etc.
        # --max-turns 1 ensures no tool-calling loops
        return [
            "hermes", "chat", "-q", prompt,
            "--quiet",
            "--ignore-rules",
            "--max-turns", "1",
        ]

    def build_env(self, original_env: dict) -> dict:
        env = original_env.copy()
        # Use bob-worker profile to avoid recursion
        env["HERMES_PROFILE"] = "bob-worker"
        # When HOME is overridden by the orchestrator, Hermes can't find
        # ~/.hermes/ profiles. Set HERMES_HOME explicitly.
        # NOTE: Use Path.home() (which uses pwd/realuid, not env HOME)
        # since original_env["HOME"] has been overridden to the isolated dir.
        env["HERMES_HOME"] = str(Path.home() / ".hermes")
        return env

    def ensure_bob_worker_profile(self) -> bool:
        """Check if bob-worker profile exists; create it if missing."""
        import subprocess
        result = subprocess.run(
            ["hermes", "profile", "list"],
            capture_output=True, text=True,
        )
        if "bob-worker" in result.stdout:
            return True

        # Auto-create by cloning from default
        subprocess.run(
            ["hermes", "profile", "create", "bob-worker", "--clone", "--no-alias"],
            capture_output=True, text=True,
        )
        print("[bob] Created bob-worker profile for isolated child processes")
        return True
