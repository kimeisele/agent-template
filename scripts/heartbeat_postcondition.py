#!/usr/bin/env python3
"""Verify that a heartbeat message reached the steward-federation hub.

Reads the hub nadi directory via ``gh api`` and checks that the
expected source node ID appears in at least one mailbox file name
produced during this heartbeat cycle.

Usage:
    python scripts/heartbeat_postcondition.py <source_node_id>

Exit codes:
    0 — expected source found in hub nadi mailbox files
    1 — postcondition not met (hub unreachable, source not found, or empty)
    2 — usage error

Requires: GH_TOKEN with read access to kimeisele/steward-federation.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_PEER_PATH = REPO_ROOT / "data" / "federation" / "peer.json"


def _get_source_node_id() -> str:
    """Return the source node ID from peer.json city_id."""
    peer = json.loads(_PEER_PATH.read_text())
    return peer.get("identity", {}).get("city_id", "unknown")


def _list_hub_nadi_files() -> list[str] | None:
    """List files in the hub nadi/ directory via gh api. Returns None on failure."""
    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        print("error: GH_TOKEN not set", file=sys.stderr)
        return None

    # List contents of nadi/ directory
    result = subprocess.run(
        [
            "gh", "api",
            "repos/kimeisele/steward-federation/contents/nadi",
            "--jq", ".[].name",
        ],
        capture_output=True, text=True, timeout=15,
        env={**os.environ, "GH_TOKEN": token},
    )
    if result.returncode != 0:
        print(
            f"error: cannot list hub nadi files: {result.stderr.strip()[:120]}",
            file=sys.stderr,
        )
        return None

    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return names


def check_hub_has_source(source_id: str) -> int:
    """Return 0 if *source_id* appears in hub nadi mailbox file names."""
    names = _list_hub_nadi_files()
    if names is None:
        return 1

    # nadi-kit writes nadi/{source}_to_{target}.json files
    prefix = f"{source_id}_to_"
    matching = [n for n in names if n.startswith(prefix)]

    if not matching:
        print(
            f"error: source '{source_id}' not found in hub nadi files. "
            f"Files seen: {', '.join(names[:10]) or '(none)'}",
            file=sys.stderr,
        )
        return 1

    print(f"Hub postcondition verified: {len(matching)} file(s) for {source_id}")
    for m in matching:
        print(f"  {m}")
    return 0


def main() -> int:
    if len(sys.argv) > 1:
        source_id = sys.argv[1]
    else:
        if not _PEER_PATH.exists():
            print("error: peer.json not found, and no source_id argument",
                  file=sys.stderr)
            return 2
        source_id = _get_source_node_id()

    return check_hub_has_source(source_id)


if __name__ == "__main__":
    raise SystemExit(main())
