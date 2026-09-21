"""
Abstract harness adapter base class.

Every harness adapter inherits from this and implements:
  - build_command(prompt) -> list[str]
  - build_env(original_env) -> dict
"""

from abc import ABC, abstractmethod
import subprocess
from pathlib import Path


class HarnessAdapter(ABC):
    NAME: str = "base"
    BINARY: str = ""

    def __init__(self, workdir: str, timeout: int = 300):
        self.workdir = workdir  # Isolated per-harness subdirectory
        self.timeout = timeout
        self.output_file = Path(workdir) / "output.txt"

    @abstractmethod
    def build_command(self, prompt: str) -> list[str]:
        """Build the CLI command for this harness."""
        ...

    @abstractmethod
    def build_env(self, original_env: dict) -> dict:
        """Build the environment dict for this harness subprocess."""
        ...

    def is_available(self) -> bool:
        """Check if this harness binary is on PATH."""
        import shutil
        return shutil.which(self.BINARY) is not None

    def run(self, prompt: str, original_env: dict) -> subprocess.CompletedProcess:
        """
        Execute the harness with the given prompt.

        The environment dict is prepared by the orchestrator (HOME override,
        PATH preservation, API keys). This method only applies harness-specific
        env additions via build_env().

        Returns subprocess.CompletedProcess with capture_output=True.
        """
        env = self.build_env(original_env)

        cmd = self.build_command(prompt)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=self.workdir,
                env=env,
            )
        except subprocess.TimeoutExpired:
            # Return a synthetic CompletedProcess on timeout
            result = subprocess.CompletedProcess(
                cmd,
                returncode=-1,
                stdout="",
                stderr=f"Harness '{self.NAME}' timed out after {self.timeout}s",
            )
        except FileNotFoundError:
            result = subprocess.CompletedProcess(
                cmd,
                returncode=-1,
                stdout="",
                stderr=f"Binary not found: {self.BINARY}",
            )
        except Exception as e:
            result = subprocess.CompletedProcess(
                cmd,
                returncode=-1,
                stdout="",
                stderr=str(e),
            )

        return result
