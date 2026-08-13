"""Provider-neutral boundary for one ephemeral headless runtime attempt."""

from .adapter import HeadlessRuntimeAdapter, RuntimeTask
from .result import RuntimeResult

__all__ = ["HeadlessRuntimeAdapter", "RuntimeResult", "RuntimeTask"]
