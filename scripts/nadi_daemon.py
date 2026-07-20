#!/usr/bin/env python3
"""NADI federation daemon — heartbeat + inbox sync for new nodes.

Requires nadi-kit. Install with: pip install -e '.[federation]'
"""

import argparse
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    from nadi_kit import NadiNode
except ImportError:
    print(
        "nadi-kit is required for federation operations.\n"
        "Install with: pip install -e '.[federation]'",
        file=sys.stderr,
    )
    raise SystemExit(1)

log = logging.getLogger("nadi_daemon")

_CANONICAL_PEER = REPO_ROOT / "data" / "federation" / "peer.json"


def handle_heartbeat(msg):
    log.info("heartbeat from %s (health=%.2f)", msg.source, msg.payload.get("health", 0))

def handle_default(msg):
    log.info("received op=%s from %s", msg.operation, msg.source)

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="NADI federation daemon")
    parser.add_argument("--once", action="store_true", help="Single sync cycle")
    parser.add_argument("--interval", type=int, default=900, help="Seconds between cycles")
    parser.add_argument("--health", type=float, default=1.0, help="Health score to report")
    parser.add_argument(
        "--head-agent",
        type=str,
        default=None,
        help="Dotted path to a HeadAgent subclass (e.g. my_agents.MyAgent). "
             "If specified, runs its heartbeat() each cycle instead of a plain NADI heartbeat.",
    )
    args = parser.parse_args()

    if not _CANONICAL_PEER.exists():
        print(
            f"ERROR: {_CANONICAL_PEER} not found. "
            f"Run scripts/setup_node.py first.",
            file=sys.stderr,
        )
        return 1

    try:
        node = NadiNode.from_peer_json(_CANONICAL_PEER)
    except Exception as exc:
        print(f"ERROR: failed to load node from {_CANONICAL_PEER}: {exc}",
              file=sys.stderr)
        return 1

    node.on("heartbeat", handle_heartbeat)
    log.info("NADI daemon started for %s (peer: %s)", node.agent_id, _CANONICAL_PEER)

    # Show outbox state on startup
    try:
        outbox = node.transport.read_outbox()
        log.info("outbox: %d pending message(s)", len(outbox))
    except Exception:
        pass

    # Load HeadAgent subclass if specified
    head_agent_instance = None
    if args.head_agent:
        try:
            import importlib
            module_path, class_name = args.head_agent.rsplit(".", 1)
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            head_agent_instance = cls(node)
            log.info("HeadAgent loaded: %s (%s)", class_name, head_agent_instance.agent_type)
        except Exception as exc:
            log.error("Failed to load HeadAgent %s: %s — falling back to plain heartbeat", args.head_agent, exc)

    cycle = 0
    while True:
        cycle += 1
        log.info("=== sync cycle %d ===", cycle)

        # HeadAgent cognitive cycle or plain heartbeat
        if head_agent_instance is not None:
            try:
                result = head_agent_instance.heartbeat()
                log.info("HeadAgent: %s", result)
            except Exception as exc:
                log.warning("HeadAgent heartbeat failed, falling back: %s", exc)
                node.heartbeat(health=args.health)
        else:
            node.heartbeat(health=args.health)

        # Full sync: pull → process → flush → push
        stats = node.sync()
        log.info("pulled=%d processed=%d pushed=%d expired=%d",
                 stats["pulled"], stats["processed"], stats["pushed"], stats["expired"])

        if args.once:
            break
        time.sleep(args.interval)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
