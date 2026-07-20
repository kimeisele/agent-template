#!/usr/bin/env python3
"""Append a message to the Nadi outbox for federation relay pickup.

Reads the outbox path from the node's ``peer.json`` so that every NADI
component uses the same canonical location.

Usage:
    python scripts/nadi_send.py --to agent-research --op inquiry --payload '{"question":"What is dark matter?"}'
    python scripts/nadi_send.py --to agent-city --op heartbeat
    python scripts/nadi_send.py --list          # show pending outbox messages
    python scripts/nadi_send.py --clear         # clear outbox after relay pickup
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Canonical NADI paths — resolved once from peer.json.
_PEER_PATH = REPO_ROOT / "data" / "federation" / "peer.json"
_CANONICAL_OUTBOX = REPO_ROOT / "data" / "federation" / "nadi_outbox.json"

_FEDERATION_INSTALL_HINT = (
    "nadi-kit is required for federation operations. "
    "Install with: pip install -e '.[federation]'"
)


def _resolve_outbox_path() -> Path | None:
    """Return the canonical outbox path from peer.json, or None on error."""
    if not _PEER_PATH.exists():
        print(
            f"error: {_PEER_PATH} not found. "
            f"Run scripts/setup_node.py first.",
            file=sys.stderr,
        )
        return None
    try:
        peer = json.loads(_PEER_PATH.read_text())
    except json.JSONDecodeError as exc:
        print(f"error: {_PEER_PATH} is not valid JSON: {exc}", file=sys.stderr)
        return None
    outbox_rel = peer.get("nadi", {}).get("outbox")
    if not outbox_rel or not isinstance(outbox_rel, str):
        print(
            "error: peer.json missing nadi.outbox path", file=sys.stderr,
        )
        return None
    # Relative paths are resolved against the repository root.
    outbox = REPO_ROOT / outbox_rel
    outbox.parent.mkdir(parents=True, exist_ok=True)
    return outbox


def _repo_name() -> str:
    """Derive this node's ID from the repo directory name."""
    return REPO_ROOT.name


def _read_outbox() -> list | None:
    """Read the outbox array.

    Returns an empty list when the file is missing or empty.
    Returns ``None`` when the file exists but is corrupt — the caller
    MUST NOT proceed with writes to preserve the original data.
    """
    outbox_path = _resolve_outbox_path()
    if outbox_path is None:
        return None
    if not outbox_path.exists():
        return []
    text = outbox_path.read_text().strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        print(
            f"error: outbox at {outbox_path} is not valid JSON ({exc}). "
            f"File has not been modified. Please repair manually.",
            file=sys.stderr,
        )
        return None
    if not isinstance(data, list):
        print(
            f"error: outbox at {outbox_path} is not a JSON array. "
            f"File has not been modified. Please repair manually.",
            file=sys.stderr,
        )
        return None
    return data


def _write_outbox(messages: list) -> bool:
    """Write *messages* to the canonical outbox.

    Returns ``True`` on success, ``False`` if the outbox path could not
    be resolved.
    """
    outbox_path = _resolve_outbox_path()
    if outbox_path is None:
        return False
    outbox_path.write_text(json.dumps(messages, indent=2, sort_keys=True) + "\n")
    return True


def build_envelope(
    target: str,
    operation: str,
    payload: dict | None = None,
    *,
    source: str | None = None,
    nadi_type: str = "filesystem",
    priority: int = 5,
    ttl_ms: int = 300_000,
) -> dict:
    """Build a DeliveryEnvelope matching the steward-federation protocol.

    Fields follow the FilesystemFederationTransport format used by
    agent-internet's relay pump.
    """
    source = source or _repo_name()
    return {
        "correlation_id": str(uuid.uuid4()),
        "envelope_id": str(uuid.uuid4()),
        "nadi_op": operation,
        "nadi_type": nadi_type,
        "operation": operation,
        "payload": payload or {},
        "priority": priority,
        "source_city_id": source,
        "target_city_id": target,
        "timestamp": time.time(),
        "ttl_ms": ttl_ms,
    }


def cmd_send(args: argparse.Namespace) -> int:
    """Append an envelope to the outbox."""
    if not args.to or not args.op:
        print("error: --to and --op are required", file=sys.stderr)
        return 1

    payload: dict | None = None
    if args.payload:
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError:
            print("error: --payload must be valid JSON", file=sys.stderr)
            return 1

    envelope = build_envelope(
        target=args.to,
        operation=args.op,
        payload=payload,
        priority=args.priority,
        ttl_ms=args.ttl,
    )

    outbox = _read_outbox()
    if outbox is None:
        return 1
    outbox.append(envelope)
    if not _write_outbox(outbox):
        return 1

    # Postcondition: re-read and verify the envelope is present.
    verify = _read_outbox()
    found = any(e.get("envelope_id") == envelope["envelope_id"] for e in verify)
    if not found:
        print("error: envelope written but re-read verification failed",
              file=sys.stderr)
        return 1

    outbox_path = _resolve_outbox_path()
    print(f"Queued envelope {envelope['envelope_id'][:8]}… → {args.to} ({args.op})")
    print(f"Outbox ({outbox_path}): {len(verify)} message(s)")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    """List pending outbox messages."""
    outbox_path = _resolve_outbox_path()
    if outbox_path is None:
        return 1
    outbox = _read_outbox()
    if outbox is None:
        return 1
    if not outbox:
        print(f"Outbox ({outbox_path}): empty.")
        return 0
    print(f"{len(outbox)} pending message(s):\n")
    for i, env in enumerate(outbox, 1):
        eid = env.get("envelope_id", "?")[:8]
        target = env.get("target_city_id", "?")
        op = env.get("operation", "?")
        print(f"  {i}. [{eid}…] → {target} ({op})")
    print(f"\nOutbox path: {outbox_path}")
    return 0


def cmd_clear(_args: argparse.Namespace) -> int:
    """Clear the outbox after postcondition verification."""
    outbox_path = _resolve_outbox_path()
    if outbox_path is None:
        return 1
    if not _write_outbox([]):
        return 1
    # Postcondition: outbox is empty.
    verify = _read_outbox()
    if len(verify) != 0:
        print("error: clear succeeded but re-read found messages",
              file=sys.stderr)
        return 1
    print(f"Outbox ({outbox_path}) cleared.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Nadi outbox message tool")
    sub = parser.add_subparsers(dest="command")

    send = sub.add_parser("send", help="Queue a message for relay")
    send.add_argument("--to", required=True, help="Target node ID (e.g. agent-research)")
    send.add_argument("--op", required=True, help="Operation name (e.g. inquiry, heartbeat)")
    send.add_argument("--payload", default=None, help="JSON payload string")
    send.add_argument("--priority", type=int, default=5, help="Priority 1-10 (default 5)")
    send.add_argument("--ttl", type=int, default=300_000, help="TTL in ms (default 300000)")

    sub.add_parser("list", help="List pending outbox messages")
    sub.add_parser("clear", help="Clear the outbox")

    # Support flat --list / --clear flags for convenience
    parser.add_argument("--list", action="store_true", help="List pending messages")
    parser.add_argument("--clear", action="store_true", help="Clear the outbox")
    # Flat send flags
    parser.add_argument("--to", default=None, help="Target node ID")
    parser.add_argument("--op", default=None, help="Operation name")
    parser.add_argument("--payload", default=None, help="JSON payload")
    parser.add_argument("--priority", type=int, default=5)
    parser.add_argument("--ttl", type=int, default=300_000)

    args = parser.parse_args()

    if args.list or args.command == "list":
        return cmd_list(args)
    if args.clear or args.command == "clear":
        return cmd_clear(args)
    if args.command == "send" or (args.to and args.op):
        return cmd_send(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
