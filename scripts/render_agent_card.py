"""Generate .well-known/agent.json (A2A-compatible Agent Card).

Reads the federation descriptor and authority charter to produce an
Agent Card that enables capability discovery by other agents and
orchestration platforms.

Usage:
    python scripts/render_agent_card.py [--output .well-known/agent.json]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _load_descriptor(repo_root: Path) -> dict:
    desc_path = repo_root / ".well-known" / "agent-federation.json"
    if desc_path.exists():
        return json.loads(desc_path.read_text())
    return {}


def _load_skills(repo_root: Path) -> list[dict]:
    caps_path = repo_root / "docs" / "authority" / "capabilities.json"
    if caps_path.exists():
        data = json.loads(caps_path.read_text())
        return data.get("skills", [])
    return [
        {
            "id": "authority-publishing",
            "name": "Authority Publishing",
            "description": "Publish canonical authority documents, charters, and surface metadata to the federation.",
        }
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Render A2A Agent Card")
    parser.add_argument("--output", default=".well-known/agent.json")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "kimeisele/agent-template"))
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    repo_owner, repo_name = args.repo.split("/", 1)
    descriptor = _load_descriptor(repo_root)
    display_name = descriptor.get("display_name", repo_name)

    card = {
        "name": display_name,
        "description": f"{display_name} — a federation node in the agent-internet.",
        "url": f"https://github.com/{repo_owner}/{repo_name}",
        "version": "1.0.0",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
        },
        "skills": _load_skills(repo_root),
        "provider": {
            "organization": repo_owner,
        },
        "federation": {
            "node_topic": "agent-federation-node",
            "descriptor_path": ".well-known/agent-federation.json",
            "authority_feed_branch": "authority-feed",
            "peer_discovery": True,
        },
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(card, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
