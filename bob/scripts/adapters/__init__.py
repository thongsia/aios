"""
Harness adapter registry.

Maps harness name strings to their adapter classes.
Only installed harnesses are registered at runtime.
"""

from .base import HarnessAdapter

# Lazy imports to avoid failures when a harness is not installed
_ADAPTERS: dict[str, type[HarnessAdapter]] = {}


def _register():
    from .opencode_adapter import OpencodeAdapter
    from .hermes_adapter import HermesAdapter
    from .qwen_code_adapter import QwenCodeAdapter
    from .dsh_adapter import DshAdapter

    _ADAPTERS["opencode"] = OpencodeAdapter
    _ADAPTERS["hermes"] = HermesAdapter
    _ADAPTERS["qwen"] = QwenCodeAdapter
    _ADAPTERS["dsh"] = DshAdapter


_register()
HARNESS_ADAPTERS = _ADAPTERS


def get_adapter(name: str) -> type[HarnessAdapter] | None:
    """Return the adapter class for a harness name, or None if unknown."""
    return HARNESS_ADAPTERS.get(name)
