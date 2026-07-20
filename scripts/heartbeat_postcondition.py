#!/usr/bin/env python3
"""Capture and verify heartbeat message IDs in the steward-federation hub.

Usage:
    python scripts/heartbeat_postcondition.py capture \
      --outbox data/federation/nadi_outbox.json \
      --output heartbeat-proof.json

    python scripts/heartbeat_postcondition.py verify \
      --proof heartbeat-proof.json

``capture`` reads the current outbox and saves the cryptographic source
node ID plus all message IDs to a proof file.

``verify`` checks that every captured message ID appears in the hub
nadi mailbox files for the captured source.  Message contents are read
via ``gh api`` and validated.

Exit codes:
    0 — all captured message IDs confirmed in hub
    1 — postcondition not met
    2 — usage or I/O error
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── capture ─────────────────────────────────────────────────────────────────


def cmd_capture(outbox_path: str, output_path: str) -> int:
    """Read outbox and save proof of pending message IDs."""
    opath = Path(outbox_path)
    if not opath.exists():
        print(f"error: outbox not found: {opath}", file=sys.stderr)
        return 2

    try:
        raw = json.loads(opath.read_text())
    except json.JSONDecodeError as exc:
        print(f"error: outbox is not valid JSON: {exc}", file=sys.stderr)
        return 2

    if not isinstance(raw, list) or not raw:
        print("error: outbox is empty or not a list", file=sys.stderr)
        return 1

    # Cryptographic source from first message
    source = raw[0].get("source", "")
    if not source:
        print("error: first message has no 'source' field", file=sys.stderr)
        return 2

    message_ids = [m.get("id") for m in raw if m.get("id")]
    if not message_ids:
        print("error: no message IDs found in outbox", file=sys.stderr)
        return 1

    proof = {
        "source_node_id": source,
        "message_ids": message_ids,
        "operations": [m.get("operation") for m in raw],
        "captured_at": time.time(),
    }

    Path(output_path).write_text(json.dumps(proof, indent=2) + "\n")
    print(f"Captured {len(message_ids)} message ID(s) from source {source}")
    for mid in message_ids:
        print(f"  {mid[:16]}…")
    return 0


# ── verify ─────────────────────────────────────────────────────────────────


def _list_hub_nadi_files() -> list[dict] | None:
    """List files in hub nadi/ directory via gh api. Returns None on failure."""
    token = (os.environ.get("GH_TOKEN") or "").strip()
    if not token:
        print("error: GH_TOKEN not set", file=sys.stderr)
        return None

    result = subprocess.run(
        ["gh", "api", "repos/kimeisele/steward-federation/contents/nadi"],
        capture_output=True, text=True, timeout=15,
        env={**os.environ, "GH_TOKEN": token},
    )
    if result.returncode != 0:
        print(f"error: cannot list hub files: {result.stderr.strip()[:120]}",
              file=sys.stderr)
        return None

    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("error: hub API returned invalid JSON", file=sys.stderr)
        return None

    if not isinstance(entries, list):
        return None
    return entries


def _fetch_hub_file(download_url: str) -> list | None:
    """Fetch and decode a single hub nadi file. Returns parsed JSON or None."""
    result = subprocess.run(
        ["gh", "api", download_url],
        capture_output=True, text=True, timeout=15,
        env={**os.environ, "GH_TOKEN": os.environ.get("GH_TOKEN", "")},
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict) and "content" in data:
        try:
            raw = base64.b64decode(data["content"]).decode("utf-8")
            return json.loads(raw)
        except Exception:
            return None
    return None


def cmd_verify(proof_path: str) -> int:
    """Verify captured message IDs exist in hub mailbox files."""
    ppath = Path(proof_path)
    if not ppath.exists():
        print(f"error: proof file not found: {ppath}", file=sys.stderr)
        return 2

    try:
        proof = json.loads(ppath.read_text())
    except json.JSONDecodeError as exc:
        print(f"error: proof file invalid: {exc}", file=sys.stderr)
        return 2

    source = proof.get("source_node_id", "")
    message_ids = proof.get("message_ids", [])
    captured_at = proof.get("captured_at", 0)

    if not source or not message_ids:
        print("error: proof missing source or message_ids", file=sys.stderr)
        return 2

    # List hub files
    entries = _list_hub_nadi_files()
    if entries is None:
        return 1

    # Find files matching source prefix
    prefix = f"{source}_to_"
    matching = [e for e in entries
                if isinstance(e, dict)
                and e.get("name", "").startswith(prefix)]

    if not matching:
        print(
            f"error: no hub files for source {source}. "
            f"Files seen: {', '.join(e.get('name', '?') for e in entries[:10]) or '(none)'}",
            file=sys.stderr,
        )
        return 1

    # Read matching files and search for captured message IDs
    found_ids: set[str] = set()
    for entry in matching:
        download_url = entry.get("download_url") or entry.get("url", "")
        if not download_url:
            continue
        content = _fetch_hub_file(download_url)
        if isinstance(content, list):
            for msg in content:
                if isinstance(msg, dict) and msg.get("id"):
                    found_ids.add(msg["id"])

    missing = [mid for mid in message_ids if mid not in found_ids]
    if missing:
        print(
            f"error: {len(missing)}/{len(message_ids)} message ID(s) "
            f"not found in hub files for source {source}",
            file=sys.stderr,
        )
        for mid in missing:
            print(f"  missing: {mid[:16]}…", file=sys.stderr)
        return 1

    # Timestamp plausibility: captured_at must be before now
    now = time.time()
    if captured_at > now + 300:
        print("error: captured_at is in the future", file=sys.stderr)
        return 1

    print(f"Hub postcondition verified: {len(message_ids)} message ID(s) "
          f"for source {source} found in {len(matching)} hub file(s)")
    for mid in message_ids:
        print(f"  confirmed: {mid[:16]}…")
    return 0


# ── CLI ─────────────────────────────────────────────────────────────────────


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Capture and verify heartbeat hub postcondition")
    sub = parser.add_subparsers(dest="command")

    cap = sub.add_parser("capture", help="Save current outbox message IDs")
    cap.add_argument("--outbox", default="data/federation/nadi_outbox.json")
    cap.add_argument("--output", default="heartbeat-proof.json")

    ver = sub.add_parser("verify", help="Verify message IDs in hub")
    ver.add_argument("--proof", default="heartbeat-proof.json")

    args = parser.parse_args()

    if args.command == "capture":
        return cmd_capture(args.outbox, args.output)
    if args.command == "verify":
        return cmd_verify(args.proof)

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
