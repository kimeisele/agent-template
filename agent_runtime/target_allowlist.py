"""Default-deny target allowlist for the FAW runtime publish step (S8).

The FAW runtime may write only to repositories, paths, and branch namespaces
that are explicitly allowed. This module is the single enforcement point:
nothing is allowed unless it appears in the allowlist. A missing or empty
allowlist denies everything (fail closed) — never allow-all.

The allowlist is a file (not scattered in code) so the policy is reviewable
and the same file can be shipped to the workflow that gates publishing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


@dataclass(frozen=True)
class AllowedTarget:
    repository: str
    paths: tuple[str, ...]
    branch_patterns: tuple[str, ...]


class TargetAllowlist:
    """Load and enforce the write-target allowlist.

    Deny-by-default: `allows(...)` returns False for anything not matched by
    an explicit entry. An unreadable, missing, or malformed allowlist file
    yields an empty allowlist (all denied).
    """

    def __init__(self, entries: list[AllowedTarget] | None = None) -> None:
        # Default: deny everything. An empty list is not an error — it is the
        # fail-closed state (S8: "empty/missing allowlist = all rejected").
        self._entries = tuple(entries or ())

    @classmethod
    def from_file(cls, path: Path) -> "TargetAllowlist":
        """Load from YAML. Missing/unreadable/malformed => empty (deny all)."""
        try:
            raw: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                return cls()
            entries_raw = raw.get("allowed_targets")
            if not isinstance(entries_raw, list):
                return cls()
            entries: list[AllowedTarget] = []
            for item in entries_raw:
                if not isinstance(item, dict):
                    continue
                repo = item.get("repository")
                if not isinstance(repo, str) or not repo:
                    continue
                paths = item.get("paths") or []
                branch_patterns = item.get("branch_patterns") or []
                entries.append(
                    AllowedTarget(
                        repository=repo,
                        paths=tuple(str(p) for p in paths if isinstance(p, str)),
                        branch_patterns=tuple(str(b) for b in branch_patterns if isinstance(b, str)),
                    )
                )
            return cls(entries)
        except (OSError, yaml.YAMLError):
            # Fail closed: unreadable/malformed allowlist denies everything.
            return cls()

    def allows(self, *, repository: str, path: str, branch: str) -> bool:
        """Deny by default. Returns True only on an exact entry match."""
        for entry in self._entries:
            if entry.repository != repository:
                continue
            if entry.paths and not any(self._path_match(pattern, path) for pattern in entry.paths):
                continue
            if entry.branch_patterns and not any(
                self._branch_match(pattern, branch) for pattern in entry.branch_patterns
            ):
                continue
            return True
        return False

    @staticmethod
    def _path_match(pattern: str, path: str) -> bool:
        if pattern == path:
            return True
        if pattern.endswith("/") and path.startswith(pattern):
            return True
        return False

    @staticmethod
    def _branch_match(pattern: str, branch: str) -> bool:
        if pattern == branch:
            return True
        if "/" in pattern and "*" in pattern:
            regex = re.escape(pattern).replace(r"\*", "[^/]+")
            return re.fullmatch(regex, branch) is not None
        return False

    def entries(self) -> list[AllowedTarget]:
        return list(self._entries)
