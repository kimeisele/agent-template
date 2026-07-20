#!/usr/bin/env python3
"""NADI federation daemon — heartbeat + inbox sync for new nodes.

Requires nadi-kit. Install with: pip install -e '.[federation]'

Modes
-----

``--once``
    Local, mutation-free diagnostic cycle:
    load peer, read outbox/inbox, report pending messages.
    No hub pull, no hub push, no heartbeat emit, no remote access.

``--once --relay``
    Exactly one real federation sync cycle including hub pull/push.

``--relay`` (with loop)
    Continuous daemon loop with hub push/pull each cycle.

Usage:
    python scripts/nadi_daemon.py --once            # local diagnostic
    python scripts/nadi_daemon.py --once --relay    # single relay cycle
    python scripts/nadi_daemon.py --relay           # continuous relay
"""

import argparse
import importlib.util
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_PEER_PATH = REPO_ROOT / "data" / "federation" / "peer.json"

log = logging.getLogger("nadi_daemon")


def _load_nadi_node():
    """Load a NadiNode from the canonical peer.json.

    Returns ``(node, None)`` on success, ``(None, exit_code)`` on failure.
    Prints a clear install hint when nadi-kit is genuinely absent.
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
            f"A findable but broken module is not the same as a missing one.",
            file=sys.stderr,
        )
        return None, 1

    if not _PEER_PATH.exists():
        print(
            f"ERROR: {_PEER_PATH} not found. "
            f"Run scripts/setup_node.py first.",
            file=sys.stderr,
        )
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


def _handle_heartbeat(msg):
    log.info("heartbeat from %s (health=%.2f)", msg.source,
             msg.payload.get("health", 0))


def _handle_default(msg):
    log.info("received op=%s from %s", msg.operation, msg.source)


def _print_local_diagnostic(node) -> int:
    """Read-only local diagnostic — no mutations, no remote access.

    Returns 0 on success, 1 if any diagnostic check fails.
    """
    try:
        outbox = node.transport.read_outbox()
        inbox = node.transport.read_inbox()
    except Exception as exc:
        log.error("transport read failed: %s", exc)
        return 1

    print(f"Node:  {node.agent_id}")
    print(f"Peer:  {_PEER_PATH}")
    print(f"Dir:   {node.transport.federation_dir}")
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


def _run_relay_cycle(node, args, cycle_count) -> int:
    """Execute one full relay cycle: heartbeat → sync.

    Returns 0 on success, 1 on sync failure.
    """
    # Heartbeat (HeadAgent or plain)
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


def main():
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
    args = parser.parse_args()

    node, exit_code = _load_nadi_node()
    if node is None:
        return exit_code

    node.on("heartbeat", _handle_heartbeat)
    node.on("*", _handle_default)

    # ── --once without --relay: local diagnostic ──
    if args.once and not args.relay:
        log.info("local diagnostic for %s", node.agent_id)
        return _print_local_diagnostic(node)

    # ── Relay modes ──
    if args.relay:
        print(
            "\n  ⚠  REMOTE RELAY ENABLED\n"
            "  Hub: kimeisele/steward-federation\n"
        )
        log.info("relay daemon started for %s", node.agent_id)

        if args.once:
            return _run_relay_cycle(node, args, 0)

        # Continuous loop
        cycle = 0
        import time
        while True:
            cycle += 1
            log.info("=== relay cycle %d ===", cycle)
            if _run_relay_cycle(node, args, cycle) != 0:
                log.warning("relay cycle %d had errors", cycle)
            time.sleep(args.interval)

    # ── Neither --once nor --relay: show help ──
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
