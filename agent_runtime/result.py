"""Neutral result values; intentionally no FAW, Nadi, or GitHub imports.

The field names mirror the canonical FAW `RuntimeResult` shape (status,
started_at, finished_at, artifacts, usage, failure, evidence) so a receipt
can be constructed from an adapter result without the runtime importing FAW.
Debug fields (exit_code, wall_seconds, output_bytes, event_count,
stdout_path, stderr_path) are adapter-local and omitted from any receipt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RuntimeResult:
    status: str
    started_at: datetime = field(default_factory=_utcnow)
    finished_at: datetime = field(default_factory=_utcnow)
    artifacts: tuple[dict[str, Any], ...] = ()
    usage: dict[str, Any] = field(default_factory=dict)
    failure: dict[str, Any] | None = None
    evidence: tuple[dict[str, Any], ...] = ()

    # Adapter-local debug fields (never part of a receipt).
    exit_code: int | None = None
    wall_seconds: float = 0.0
    output_bytes: int = 0
    event_count: int = 0
    stdout_path: Path | None = None
    stderr_path: Path | None = None
