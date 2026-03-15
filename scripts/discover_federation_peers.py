"""Discover federation peers via the GitHub API (curl-only).

Searches GitHub for repositories with the ``agent-federation-node`` topic,
fetches each peer's ``.well-known/agent-federation.json``, and writes a
local peer registry.

Requires either ``GITHUB_TOKEN`` env-var or unauthenticated access.

Usage:
    python scripts/discover_federation_peers.py [--output .federation/peers.json]
    python scripts/discover_federation_peers.py --org kimeisele
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


TOPIC = "agent-federation-node"
SEARCH_API = "https://api.github.com/search/repositories"
RAW_BASE = "https://raw.githubusercontent.com"


def _curl_json(url: str, token: str | None = None) -> dict | list | None:
    """Fetch JSON from *url* using curl.  Returns None on failure."""
    cmd = ["curl", "-sf", "-H", "Accept: application/json"]
    if token:
        cmd += ["-H", f"Authorization: token {token}"]
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _fetch_descriptor(full_name: str, default_branch: str, token: str | None) -> dict | None:
    url = f"{RAW_BASE}/{full_name}/{default_branch}/.well-known/agent-federation.json"
    return _curl_json(url, token)


def _fetch_agent_card(full_name: str, default_branch: str, token: str | None) -> dict | None:
    url = f"{RAW_BASE}/{full_name}/{default_branch}/.well-known/agent.json"
    return _curl_json(url, token)


def discover(
    *,
    token: str | None = None,
    org: str | None = None,
    exclude_self: str | None = None,
) -> list[dict]:
    """Return a list of peer records discovered from GitHub."""
    query = f"topic:{TOPIC}"
    if org:
        query += f" org:{org}"
    url = f"{SEARCH_API}?q={query}&per_page=100"
    data = _curl_json(url, token)
    if not data or "items" not in data:
        print("warning: GitHub search returned no results", file=sys.stderr)
        return []

    peers: list[dict] = []
    for repo in data["items"]:
        full_name = repo["full_name"]
        if exclude_self and full_name == exclude_self:
            continue
        default_branch = repo.get("default_branch", "main")

        descriptor = _fetch_descriptor(full_name, default_branch, token)
        agent_card = _fetch_agent_card(full_name, default_branch, token)

        peer: dict = {
            "full_name": full_name,
            "html_url": repo["html_url"],
            "default_branch": default_branch,
            "description": repo.get("description") or "",
            "topics": repo.get("topics", []),
        }
        if descriptor:
            peer["federation_descriptor"] = descriptor
        if agent_card:
            peer["agent_card"] = agent_card

        peers.append(peer)

    return peers


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover federation peers via GitHub API")
    parser.add_argument("--output", default=".federation/peers.json")
    parser.add_argument("--org", help="Limit discovery to a specific GitHub org")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    peers = discover(token=token, org=args.org, exclude_self=args.repo or None)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    registry = {
        "kind": "federation_peer_registry",
        "version": 1,
        "peer_count": len(peers),
        "peers": peers,
    }
    output.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")
    print(f"Discovered {len(peers)} peer(s) → {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
