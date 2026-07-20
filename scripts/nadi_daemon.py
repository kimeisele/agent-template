#!/usr/bin/env python3
"""NADI federation daemon — heartbeat + inbox sync for new nodes.

Requires nadi-kit. Install with: pip install -e '.[federation]'

Modes
-----

``--once``
    Strictly read-only local diagnostic.
    Reads peer.json, outbox, and inbox via NadiTransport directly.
    No NadiNode construction, no key generation, no file creation,
    no heartbeat, no hub access, no mutations of any kind.

``--once --relay``
    Exactly one real federation sync cycle with hub pull/push.
    Requires a NadiNode (keys, signatures) and ``--relay`` flag.

``--relay``
    Continuous daemon loop with heartbeat + hub pull/push each cycle.

Usage:
    python scripts/nadi_daemon.py --once            # local diagnostic
    python scripts/nadi_daemon.py --once --relay    # single relay cycle
    python scripts/nadi_daemon.py --relay           # continuous relay
"""

import argparse
import importlib.util
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_PEER_PATH = REPO_ROOT / "data" / "federation" / "peer.json"

log = logging.getLogger("nadi_daemon")


# ── Path validation ─────────────────────────────────────────────────────────


def _validate_nadi_paths(peer_path: Path) -> tuple[Path, list[str]]:
    """Read *peer_path* and validate the NADI path contract.

    Returns ``(federation_dir, [])`` on success.
    Returns ``(None, errors)`` if validation fails.

    The actual nadi-kit transport contract is::

        federation_dir = peer_path.parent
        outbox = federation_dir / "nadi_outbox.json"
        inbox  = federation_dir / "nadi_inbox.json"

    If the peer declares ``nadi.outbox`` / ``nadi.inbox``, those MUST
    resolve to the exact same paths.
    """
    errors: list[str] = []
    if not peer_path.exists():
        errors.append(f"peer.json not found: {peer_path}")
        return None, errors

    try:
        peer = json.loads(peer_path.read_text())
    except json.JSONDecodeError as exc:
        errors.append(f"peer.json is not valid JSON: {exc}")
        return None, errors

    federation_dir = peer_path.parent

    # Repo root is two levels up:
    # peer.json at <repo_root>/data/federation/peer.json
    repo_root_from_peer = federation_dir.parent.parent

    # Validate declarative nadi.outbox / nadi.inbox if present
    for key, filename in [("outbox", "nadi_outbox.json"),
                          ("inbox", "nadi_inbox.json")]:
        declared = peer.get("nadi", {}).get(key)
        if declared and isinstance(declared, str):
            resolved = (repo_root_from_peer / declared).resolve()
            actual = (federation_dir / filename).resolve()
            if resolved != actual:
                errors.append(
                    f"nadi.{key} declares {declared} "
                    f"(resolves to {resolved}), "
                    f"but actual transport path is {actual}"
                )

    if errors:
        return None, errors
    return federation_dir, []


# ── nadi-kit loader (for relay modes) ───────────────────────────────────────


def _load_nadi_node():
    """Load a NadiNode from the canonical peer.json.

    **WARNING:** This constructs a full NadiNode which generates keys
    via NodeKeyStore.ensure_keys().  Only use for relay modes, NOT for
    read-only diagnostics.

    Returns ``(node, None)`` on success, ``(None, exit_code)`` on failure.
    """
    if importlib.util.find_spec("nadi_kit") is None:
        print(
            "nadi-kit is not installed.\n"
            "Install with: pip install -e '.[federation]'",
            file=sys.stderr,
        )
        return None, 1

    try:
        from nadi_kit import NadiNode  # noqa: E402
    except ImportError as exc:
        print(
            f"error: nadi-kit import failed ({exc}). "
            f"Module is findable but broken — not treated as absent.",
            file=sys.stderr,
        )
        return None, 1

    # Validate paths before constructing the node (which creates keys)
    fed_dir, errors = _validate_nadi_paths(_PEER_PATH)
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        return None, 1

    try:
        node = NadiNode.from_peer_json(_PEER_PATH)
    except Exception as exc:
        print(
            f"ERROR: failed to load node from {_PEER_PATH}: {exc}",
            file=sys.stderr,
        )
        return None, 1

    return node, 0


# ── Local diagnostic (read-only, no NadiNode) ───────────────────────────────


def _do_local_diagnostic() -> int:
    """Read-only local diagnostic — no NadiNode, no keys, no mutations."""
    # Validate paths (reads peer.json, no side effects)
    fed_dir, errors = _validate_nadi_paths(_PEER_PATH)
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        return 1

    # Read peer.json for identity info
    peer = json.loads(_PEER_PATH.read_text())
    city_id = peer.get("identity", {}).get("city_id", "unknown")

    # Use NadiTransport directly for reading (creates no files, no keys)
    from nadi_kit import NadiTransport  # noqa: E402
    transport = NadiTransport(str(fed_dir))

    try:
        outbox = transport.read_outbox()
        inbox = transport.read_inbox()
    except Exception as exc:
        log.error("transport read failed: %s", exc)
        return 1

    print(f"Node:  {city_id}")
    print(f"Peer:  {_PEER_PATH}")
    print(f"Dir:   {fed_dir}")
    print(f"Outbox: {len(outbox)} pending message(s)")
    for msg in outbox[:5]:
        print(f"  [{msg.id[:8]}…] → {msg.target} ({msg.operation}) "
              f"ttl={msg.ttl_s}s")
    if len(outbox) > 5:
        print(f"  … and {len(outbox) - 5} more")
    print(f"Inbox:  {len(inbox)} message(s)")
    for msg in inbox[:5]:
        print(f"  [{msg.id[:8]}…] ← {msg.source} ({msg.operation})")
    if len(inbox) > 5:
        print(f"  … and {len(inbox) - 5} more")

    return 0


# ── Relay modes (requires NadiNode) ─────────────────────────────────────────


def _handle_heartbeat(msg):
    log.info("heartbeat from %s (health=%.2f)", msg.source,
             msg.payload.get("health", 0))


def _handle_default(msg):
    log.info("received op=%s from %s", msg.operation, msg.source)


def _run_relay_cycle(node, args) -> int:
    """Execute one full relay cycle: heartbeat → sync.  Returns 0 on success."""
    if args.head_agent:
        try:
            import importlib as _il
            module_path, class_name = args.head_agent.rsplit(".", 1)
            mod = _il.import_module(module_path)
            cls = getattr(mod, class_name)
            head_instance = cls(node)
            head_instance.heartbeat()
        except Exception as exc:
            log.warning("HeadAgent failed: %s", exc)
            node.heartbeat(health=args.health)
    else:
        node.heartbeat(health=args.health)

    try:
        stats = node.sync()
        log.info(
            "pulled=%d processed=%d pushed=%d expired=%d",
            stats.get("pulled", 0), stats.get("processed", 0),
            stats.get("pushed", 0), stats.get("expired", 0),
        )
    except Exception as exc:
        log.error("sync failed: %s", exc)
        return 1

    return 0


def _execute_mode(args, node_loader=_load_nadi_node) -> int:
    """Execute the daemon mode described by *args*.

    *node_loader* is a callable returning ``(node, exit_code)``.
    Injected for testability.
    """
    # ── --once without --relay: read-only local diagnostic ──
    if args.once and not args.relay:
        return _do_local_diagnostic()

    # ── Relay modes require NadiNode ──
    if args.relay:
        node, exit_code = node_loader()
        if node is None:
            return exit_code

        node.on("heartbeat", _handle_heartbeat)
        node.on("*", _handle_default)

        print(
            "\n  ⚠  REMOTE RELAY ENABLED\n"
            "  Hub: kimeisele/steward-federation\n"
        )
        log.info("relay daemon started for %s", node.agent_id)

        if args.once:
            return _run_relay_cycle(node, args)

        # Continuous loop
        cycle = 0
        import time
        while True:
            cycle += 1
            log.info("=== relay cycle %d ===", cycle)
            if _run_relay_cycle(node, args) != 0:
                log.warning("relay cycle %d had errors", cycle)
            time.sleep(args.interval)

    # ── Neither --once nor --relay: show help ──
    return 1


# ── CLI ─────────────────────────────────────────────────────────────────────


def main(argv=None, *, node_loader=_load_nadi_node) -> int:
    """Entry point.  *argv* and *node_loader* are injectable for tests."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="NADI federation daemon")
    parser.add_argument("--once", action="store_true",
                        help="Single cycle (local diagnostic unless --relay)")
    parser.add_argument("--relay", action="store_true",
                        help="Enable hub pull/push (REQUIRED for remote sync)")
    parser.add_argument("--interval", type=int, default=900,
                        help="Seconds between relay cycles (default 900)")
    parser.add_argument("--health", type=float, default=1.0,
                        help="Health score to report")
    parser.add_argument("--head-agent", type=str, default=None,
                        help="Dotted path to a HeadAgent subclass")
    if argv is None:
        argv = sys.argv[1:]
    args = parser.parse_args(argv)

    if not args.once and not args.relay:
        parser.print_help()
        return 1

    return _execute_mode(args, node_loader=node_loader)


if __name__ == "__main__":
    raise SystemExit(main())
