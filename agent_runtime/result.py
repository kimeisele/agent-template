"""Neutral result values; intentionally no FAW, Nadi, or GitHub imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RuntimeResult:
    status: str
    exit_code: int | None
    wall_seconds: float
    output_bytes: int
    event_count: int
    stdout_path: Path
    stderr_path: Path
    failure: dict[str, str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
