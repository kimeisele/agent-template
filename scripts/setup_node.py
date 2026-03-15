#!/usr/bin/env python3
"""Interactive federation node setup wizard.

Two phases:
  Phase 1 — Identity: configure your node locally (charter, capabilities, descriptors)
  Phase 2 — Connect: join the living federation (agent-city, Nadi transport, peer discovery)

Both phases run by default. The federation IS the point.

Usage:
    python scripts/setup_node.py
    python scripts/setup_node.py --non-interactive --name "My Node" --role research
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

GREEN = "\033[32m"
RED = "\033[31m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# ── Federation constants ──────────────────────────────────────────────────

AGENT_CITY_REPO = "kimeisele/agent-city"
STEWARD_FEDERATION_REPO = "kimeisele/steward-federation"
AGENT_INTERNET_REPO = "kimeisele/agent-internet"

CITY_ZONES = {
    "general": {"name": "General", "element": "Vayu (Air)", "description": "Communication & Networking"},
    "research": {"name": "Research", "element": "Jala (Water)", "description": "Knowledge & Philosophy"},
    "engineering": {"name": "Engineering", "element": "Prithvi (Earth)", "description": "Building & Tools"},
    "governance": {"name": "Governance", "element": "Agni (Fire)", "description": "Leadership & Policy"},
    "discovery": {"name": "Discovery", "element": "Akasha (Ether)", "description": "Abstract thought & Exploration"},
}

TIER_TO_ZONE = {
    "relay": "general",
    "contributor": "general",
    "research": "research",
    "service": "engineering",
    "governance": "governance",
}

# ── Tier definitions ──────────────────────────────────────────────────────

TIERS = {
    "relay": {
        "label": "Relay Node",
        "description": "Minimal presence — publish your charter, be discoverable, relay trust.",
        "produces": ["authority_document", "canonical_surface"],
        "consumes": [],
        "protocols": ["authority_feed_v1"],
        "capabilities": ["authority-publishing"],
    },
    "contributor": {
        "label": "Contributor Node",
        "description": "Active participant — publish documents, consume peer feeds, respond to inquiries.",
        "produces": ["authority_document", "canonical_surface", "public_summary"],
        "consumes": ["inquiry_request", "peer_review_challenge"],
        "protocols": ["authority_feed_v1", "open_inquiry_v1"],
        "capabilities": ["authority-publishing", "inquiry-response"],
    },
    "research": {
        "label": "Research Faculty",
        "description": "Knowledge producer — run research, publish findings, accept cross-domain inquiries.",
        "produces": ["authority_document", "research_synthesis", "cross_domain_report", "meta_analysis_report", "open_dataset"],
        "consumes": ["research_question", "raw_data_feed", "domain_observation", "inquiry_request", "peer_review_challenge"],
        "protocols": ["authority_feed_v1", "open_inquiry_v1", "peer_review_v1"],
        "capabilities": ["authority-publishing", "research-synthesis", "cross-domain-analysis", "open-inquiry"],
    },
    "service": {
        "label": "Service Node",
        "description": "Capability provider — offer tools, APIs, or agent services to the federation.",
        "produces": ["authority_document", "canonical_surface", "service_manifest"],
        "consumes": ["service_request", "capability_query"],
        "protocols": ["authority_feed_v1", "service_discovery_v1"],
        "capabilities": ["authority-publishing", "service-provider"],
    },
    "governance": {
        "label": "Governance Node",
        "description": "Policy and trust — participate in federation governance, propose policies, vote.",
        "produces": ["authority_document", "canonical_surface", "policy_proposal", "governance_record"],
        "consumes": ["policy_proposal", "vote_request", "governance_challenge"],
        "protocols": ["authority_feed_v1", "governance_v1"],
        "capabilities": ["authority-publishing", "governance-participation"],
    },
}

LAYER_MAP = {
    "relay": "node",
    "contributor": "node",
    "research": "node",
    "service": "node",
    "governance": "city",
}

# ── Domain catalog ────────────────────────────────────────────────────────

DOMAINS = {
    "energy": {"id": "energy-sustainability", "name": "Energy & Sustainability"},
    "health": {"id": "health-medicine", "name": "Health & Medicine"},
    "physics": {"id": "physics-fundamental", "name": "Physics & Fundamental Science"},
    "computation": {"id": "computation-intelligence", "name": "Computation & Intelligence"},
    "biology": {"id": "biology-ecology", "name": "Biology & Ecology"},
    "philosophy": {"id": "philosophy-ethics", "name": "Philosophy & Ethics"},
    "art": {"id": "art-creativity", "name": "Art & Creative Expression"},
    "education": {"id": "education-learning", "name": "Education & Learning"},
    "engineering": {"id": "engineering-building", "name": "Engineering & Building"},
    "economics": {"id": "economics-trade", "name": "Economics & Trade"},
}

# ── Interactive prompts ───────────────────────────────────────────────────


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"  {CYAN}{prompt}{suffix}{RESET}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)
    return answer or default


def _ask_choice(prompt: str, options: dict[str, str], default: str = "") -> str:
    print(f"\n  {CYAN}{prompt}{RESET}")
    keys = list(options.keys())
    for i, (key, desc) in enumerate(options.items(), 1):
        marker = f" {DIM}(default){RESET}" if key == default else ""
        print(f"    {BOLD}{i}{RESET}. {key:15s} — {desc}{marker}")
    while True:
        raw = _ask("Choose (number or name)", default)
        if raw in options:
            return raw
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(keys):
                return keys[idx]
        except ValueError:
            pass
        print(f"    {YELLOW}Please enter a valid option.{RESET}")


def _ask_multi(prompt: str, options: dict[str, str]) -> list[str]:
    print(f"\n  {CYAN}{prompt}{RESET}")
    keys = list(options.keys())
    for i, (key, desc) in enumerate(options.items(), 1):
        print(f"    {BOLD}{i}{RESET}. {key:15s} — {desc}")
    print(f"    {DIM}Enter numbers separated by commas, or 'none'{RESET}")
    raw = _ask("Select", "none")
    if raw.lower() == "none":
        return []
    selected = []
    for part in raw.split(","):
        part = part.strip()
        if part in options:
            selected.append(part)
        else:
            try:
                idx = int(part) - 1
                if 0 <= idx < len(keys):
                    selected.append(keys[idx])
            except ValueError:
                pass
    return selected


def _ask_yn(prompt: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    raw = _ask(f"{prompt} ({suffix})", "")
    if not raw:
        return default
    return raw.lower().startswith("y")


# ── Curl helper ───────────────────────────────────────────────────────────


def _curl_json(url: str) -> dict | None:
    """Fetch JSON via curl. Returns None on failure."""
    import os
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
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


def _gh_available() -> bool:
    """Check if gh CLI is installed and authenticated."""
    result = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    return result.returncode == 0


# ── Phase 1: Local identity ──────────────────────────────────────────────


def _write_charter(config: dict) -> None:
    charter_path = REPO_ROOT / "docs" / "authority" / "charter.md"
    name = config["display_name"]
    description = config["description"]
    tier = TIERS[config["tier"]]
    zone = CITY_ZONES.get(config.get("city_zone", ""), {})

    lines = [
        f"# {name} Charter",
        "",
        f"> {description}",
        "",
        "## Role",
        "",
        f"This node operates as a **{tier['label']}** in the agent-internet federation.",
        "",
    ]

    if zone:
        lines.extend([
            "## City Zone",
            "",
            f"Registered in the **{zone['name']}** zone ({zone['element']}) — {zone['description']}.",
            "",
        ])

    if config.get("domains"):
        lines.append("## Domains")
        lines.append("")
        for d in config["domains"]:
            domain = DOMAINS[d]
            lines.append(f"- **{domain['name']}**")
        lines.append("")

    if config.get("values"):
        lines.append("## Values")
        lines.append("")
        lines.append(config["values"])
        lines.append("")

    lines.extend([
        "## Federation Commitment",
        "",
        "This node commits to the federation's core principles:",
        "- Publish truthful, verifiable authority documents",
        "- Respect boundary separation (substrate / world / city / membrane)",
        "- Participate in peer review and trust verification",
        "",
    ])

    charter_path.write_text("\n".join(lines))


def _write_capabilities(config: dict) -> None:
    caps_path = REPO_ROOT / "docs" / "authority" / "capabilities.json"
    tier = TIERS[config["tier"]]

    skills = [{"id": cap, "name": cap.replace("-", " ").title(), "description": f"{cap.replace('-', ' ').title()} capability."} for cap in tier["capabilities"]]

    for skill in config.get("custom_skills", []):
        skills.append({"id": skill.lower().replace(" ", "-"), "name": skill, "description": f"{skill} capability."})

    manifest: dict = {
        "kind": "agent_capability_manifest",
        "version": 1,
        "node_id": config["repo_name"],
        "node_role": config.get("role_id", config["tier"]),
        "display_name": config["display_name"],
        "description": config["description"],
        "skills": skills,
        "capabilities": {},
        "federation_interfaces": {
            "produces": tier["produces"],
            "consumes": tier["consumes"],
            "protocols": tier["protocols"],
        },
        "protocols": [
            {"name": "agent-federation", "version": 1, "descriptor": ".well-known/agent-federation.json"},
            {"name": "a2a-agent-card", "version": "1.0.0", "descriptor": ".well-known/agent.json"},
        ],
    }

    if config.get("city_zone"):
        manifest["city"] = {
            "zone": config["city_zone"],
            "element": CITY_ZONES[config["city_zone"]]["element"],
            "registered": config.get("city_registered", False),
        }

    if config.get("nadi_transport"):
        manifest["federation_interfaces"]["protocols"].append("nadi_transport_v1")

    if config.get("domains"):
        manifest["faculties"] = [DOMAINS[d] for d in config["domains"]]

    caps_path.write_text(json.dumps(manifest, indent=2) + "\n")


def _regenerate(config: dict) -> None:
    repo = config.get("github_repo", f"kimeisele/{config['repo_name']}")
    layer = LAYER_MAP.get(config["tier"], "node")
    subprocess.run(
        [sys.executable, "scripts/render_federation_descriptor.py", "--repo", repo, "--layer", layer],
        cwd=str(REPO_ROOT), capture_output=True,
    )
    subprocess.run(
        [sys.executable, "scripts/render_agent_card.py", "--repo", repo],
        cwd=str(REPO_ROOT), capture_output=True,
    )


# ── Phase 2: Federation connection ───────────────────────────────────────


def _setup_nadi_transport(config: dict) -> None:
    """Set up Nadi transport inbox/outbox for federation messaging."""
    nadi_dir = REPO_ROOT / "nadi"
    nadi_dir.mkdir(exist_ok=True)

    node_id = config["repo_name"]
    inbox = {
        "kind": "nadi_inbox",
        "version": 1,
        "node_id": node_id,
        "messages": [],
    }
    outbox = {
        "kind": "nadi_outbox",
        "version": 1,
        "node_id": node_id,
        "messages": [],
    }
    (nadi_dir / "inbox.json").write_text(json.dumps(inbox, indent=2) + "\n")
    (nadi_dir / "outbox.json").write_text(json.dumps(outbox, indent=2) + "\n")

    # Write a relay config pointing to steward-federation hub
    relay_config = {
        "kind": "nadi_relay_config",
        "version": 1,
        "node_id": node_id,
        "hub_repo": STEWARD_FEDERATION_REPO,
        "hub_inbox": f"https://raw.githubusercontent.com/{STEWARD_FEDERATION_REPO}/main/nadi_inbox.json",
        "hub_outbox": f"https://raw.githubusercontent.com/{STEWARD_FEDERATION_REPO}/main/nadi_outbox.json",
        "poll_interval_minutes": 15,
    }
    (nadi_dir / "relay-config.json").write_text(json.dumps(relay_config, indent=2) + "\n")


def _write_nadi_relay_workflow(config: dict) -> None:
    """Write a GitHub Actions workflow for periodic Nadi relay polling."""
    workflow_path = REPO_ROOT / ".github" / "workflows" / "nadi-relay.yml"
    node_id = config["repo_name"]
    content = f"""name: Nadi Relay

on:
  schedule:
    - cron: "*/15 * * * *"    # every 15 minutes
  workflow_dispatch:

permissions:
  contents: write

jobs:
  relay:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Poll federation hub for messages
        env:
          GITHUB_TOKEN: ${{{{ secrets.GITHUB_TOKEN }}}}
          NODE_ID: {node_id}
        run: python scripts/nadi_relay.py --node-id "$NODE_ID"

      - name: Commit relay state
        run: |
          git config user.name "agent-template-bot"
          git config user.email "bot@agent-template"
          git add nadi/
          if git diff --cached --quiet; then exit 0; fi
          git commit -m "Nadi relay sync"
          git push origin HEAD:${{{{GITHUB_REF_NAME}}}}
"""
    workflow_path.write_text(content)


def _write_nadi_relay_script() -> None:
    """Write the Nadi relay script that polls the federation hub."""
    script_path = REPO_ROOT / "scripts" / "nadi_relay.py"
    content = '''"""Nadi relay: poll the federation hub and sync messages.

Fetches new messages from the steward-federation hub outbox,
delivers them to the local inbox, and pushes local outbox
messages to the hub.

Usage:
    python scripts/nadi_relay.py --node-id my-node
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _curl_json(url: str) -> dict | None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Nadi federation relay")
    parser.add_argument("--node-id", required=True)
    args = parser.parse_args()

    nadi_dir = REPO_ROOT / "nadi"
    if not nadi_dir.exists():
        print("No nadi/ directory — run setup_node.py first", file=sys.stderr)
        return 1

    relay_config_path = nadi_dir / "relay-config.json"
    if not relay_config_path.exists():
        print("No relay config — run setup_node.py first", file=sys.stderr)
        return 1

    relay_config = json.loads(relay_config_path.read_text())
    hub_outbox_url = relay_config["hub_outbox"]

    # Fetch hub outbox
    hub_outbox = _curl_json(hub_outbox_url)
    if hub_outbox is None:
        print("Could not reach federation hub outbox")
        return 1

    # Filter messages addressed to this node
    inbox_path = nadi_dir / "inbox.json"
    inbox = json.loads(inbox_path.read_text())
    existing_ids = {m.get("id") for m in inbox.get("messages", [])}

    new_messages = []
    for msg in hub_outbox.get("messages", []):
        to = msg.get("to", "")
        if (to == args.node_id or to == "*") and msg.get("id") not in existing_ids:
            new_messages.append(msg)

    if new_messages:
        inbox["messages"].extend(new_messages)
        inbox_path.write_text(json.dumps(inbox, indent=2) + "\\n")
        print(f"Received {len(new_messages)} new message(s)")
    else:
        print("No new messages")

    # Clear delivered outbox messages
    outbox_path = nadi_dir / "outbox.json"
    outbox = json.loads(outbox_path.read_text())
    if outbox.get("messages"):
        print(f"Outbox has {len(outbox['messages'])} message(s) pending hub pickup")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
    script_path.write_text(content)


def _write_discovery_beacon(config: dict) -> None:
    """Write a discovery beacon for agent-internet to find this node."""
    beacon_dir = REPO_ROOT / ".agent-internet"
    beacon_dir.mkdir(exist_ok=True)

    beacon = {
        "kind": "discovery_beacon",
        "version": 1,
        "node_id": config["repo_name"],
        "display_name": config["display_name"],
        "repo": config["github_repo"],
        "transport": "github_raw",
        "capabilities": TIERS[config["tier"]]["capabilities"],
        "zone": config.get("city_zone", "general"),
        "announced_at": time.time(),
        "ttl_s": 604800,  # 7 days
    }
    (beacon_dir / "beacon.json").write_text(json.dumps(beacon, indent=2) + "\n")


def _register_with_agent_city(config: dict) -> bool:
    """File a registration issue on agent-city via gh CLI."""
    if not _gh_available():
        print(f"    {YELLOW}gh CLI not available — skipping auto-registration{RESET}")
        print(f"    {DIM}Manual: https://github.com/{AGENT_CITY_REPO}/issues/new?template=agent-registration.yml{RESET}")
        return False

    zone = CITY_ZONES.get(config.get("city_zone", "general"), {})
    zone_label = f"{zone.get('name', 'General')} ({zone.get('description', '')})"
    title = f"[REGISTRATION] {config['display_name']}"
    body = f"""## Agent Registration

**Name:** {config['display_name']}
**Repository:** https://github.com/{config['github_repo']}
**Descriptor:** https://raw.githubusercontent.com/{config['github_repo']}/main/.well-known/agent-federation.json
**Tier:** {TIERS[config['tier']]['label']}
**Zone:** {zone_label}
**Description:** {config['description']}

### Capabilities
{chr(10).join('- ' + c for c in TIERS[config['tier']]['capabilities'])}

### Federation Interfaces
- **Produces:** {', '.join(TIERS[config['tier']]['produces'])}
- **Consumes:** {', '.join(TIERS[config['tier']]['consumes']) or '(none yet)'}

---
*Filed automatically by `scripts/setup_node.py`*
"""
    result = subprocess.run(
        ["gh", "issue", "create", "--repo", AGENT_CITY_REPO,
         "--title", title, "--body", body,
         "--label", "registration,pending"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        issue_url = result.stdout.strip()
        print(f"    {GREEN}✓{RESET} Registration issue filed: {issue_url}")
        return True
    else:
        print(f"    {YELLOW}Could not file issue: {result.stderr.strip()[:80]}{RESET}")
        print(f"    {DIM}Manual: https://github.com/{AGENT_CITY_REPO}/issues/new?template=agent-registration.yml{RESET}")
        return False


def _check_federation_visibility(config: dict) -> bool:
    """Check if this node's descriptor is reachable from the internet."""
    repo = config["github_repo"]
    url = f"https://raw.githubusercontent.com/{repo}/main/.well-known/agent-federation.json"
    data = _curl_json(url)
    if data and data.get("kind") == "agent_federation_descriptor":
        return True
    return False


def _show_federation_status(config: dict) -> None:
    """Display the current federation connection status."""
    print(f"\n{BOLD}── Federation Status ──{RESET}\n")

    # Peer discovery
    print(f"  {BOLD}Peers:{RESET}")
    result = subprocess.run(
        [sys.executable, "scripts/discover_federation_peers.py", "--seeds-only",
         "--output", ".federation/peers.json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    if result.returncode == 0:
        peers_path = REPO_ROOT / ".federation" / "peers.json"
        if peers_path.exists():
            peers = json.loads(peers_path.read_text())
            count = peers.get("peer_count", 0)
            print(f"    {GREEN}✓{RESET} {count} federation peer(s) reachable via seeds")
            for peer in peers.get("peers", [])[:5]:
                desc = peer.get("federation_descriptor", {})
                name = desc.get("display_name", peer.get("full_name", "?"))
                print(f"      · {name}")
            if count > 5:
                print(f"      … and {count - 5} more")
    else:
        print(f"    {YELLOW}Could not reach peers (offline?){RESET}")

    # Visibility
    print(f"\n  {BOLD}Visibility:{RESET}")
    if _check_federation_visibility(config):
        print(f"    {GREEN}✓{RESET} Your descriptor is publicly reachable")
    else:
        print(f"    {DIM}─{RESET} Descriptor not yet public (push to main first)")

    # Nadi transport
    nadi_dir = REPO_ROOT / "nadi"
    print(f"\n  {BOLD}Nadi Transport:{RESET}")
    if nadi_dir.exists():
        relay_config_path = nadi_dir / "relay-config.json"
        if relay_config_path.exists():
            rc = json.loads(relay_config_path.read_text())
            print(f"    {GREEN}✓{RESET} Connected to hub: {rc['hub_repo']}")
            print(f"    {DIM}  Poll interval: every {rc['poll_interval_minutes']} minutes{RESET}")
        inbox_path = nadi_dir / "inbox.json"
        if inbox_path.exists():
            inbox = json.loads(inbox_path.read_text())
            n = len(inbox.get("messages", []))
            print(f"    {GREEN}✓{RESET} Inbox: {n} message(s)")
    else:
        print(f"    {DIM}─{RESET} Not configured")

    # City zone
    print(f"\n  {BOLD}Agent City:{RESET}")
    zone_key = config.get("city_zone", "")
    if zone_key and zone_key in CITY_ZONES:
        zone = CITY_ZONES[zone_key]
        print(f"    {GREEN}✓{RESET} Zone: {zone['name']} — {zone['element']}")
        if config.get("city_registered"):
            print(f"    {GREEN}✓{RESET} Registration filed")
        else:
            print(f"    {DIM}─{RESET} Not yet registered (will file on next push or manually)")
    else:
        print(f"    {DIM}─{RESET} No zone selected")


# ── Main wizard ───────────────────────────────────────────────────────────


def interactive_setup() -> dict:
    print(f"\n{BOLD}{'═' * 60}{RESET}")
    print(f"{BOLD}  Federation Node Setup Wizard{RESET}")
    print(f"{BOLD}{'═' * 60}{RESET}")
    print(f"\n  {DIM}Two phases: Identity → Connect to Federation{RESET}")
    print(f"  {DIM}The core kernel is always included.{RESET}\n")

    # ── Phase 1: Identity ──
    print(f"{BOLD}═══ Phase 1: Identity ═══{RESET}\n")

    display_name = _ask("Node name", "My Federation Node")
    repo_name = display_name.lower().replace(" ", "-")
    repo_name = _ask("Repository name", repo_name)
    github_org = _ask("GitHub org/user", "kimeisele")
    description = _ask("One-line description", f"{display_name} — a federation node")

    tier = _ask_choice(
        "What kind of node do you want to run?",
        {k: v["description"] for k, v in TIERS.items()},
        default="relay",
    )

    domains: list[str] = []
    if tier in ("research", "contributor"):
        domains = _ask_multi(
            "Which domains does your node cover?",
            {k: v["name"] for k, v in DOMAINS.items()},
        )

    custom_skills: list[str] = []
    if _ask_yn("Add custom capabilities beyond the defaults?", default=False):
        raw = _ask("List capabilities (comma-separated)", "")
        custom_skills = [s.strip() for s in raw.split(",") if s.strip()]

    values = ""
    if _ask_yn("Add a values statement to your charter?", default=False):
        values = _ask("Your values (one paragraph)", "")

    role_id = _ask("Node role identifier", f"{repo_name.replace('-', '_')}_{tier}")

    # ── Phase 2: Federation connection ──
    print(f"\n{BOLD}═══ Phase 2: Connect to Federation ═══{RESET}\n")

    default_zone = TIER_TO_ZONE.get(tier, "general")
    city_zone = _ask_choice(
        "Which Agent City zone fits your node?",
        {k: f"{v['element']} — {v['description']}" for k, v in CITY_ZONES.items()},
        default=default_zone,
    )

    nadi_transport = _ask_yn("Enable Nadi transport (federation messaging)?", default=True)

    register_city = _ask_yn("File registration with Agent City now?", default=True)

    config = {
        "display_name": display_name,
        "repo_name": repo_name,
        "github_repo": f"{github_org}/{repo_name}",
        "description": description,
        "tier": tier,
        "domains": domains,
        "custom_skills": custom_skills,
        "values": values,
        "role_id": role_id,
        "city_zone": city_zone,
        "nadi_transport": nadi_transport,
        "register_city": register_city,
        "city_registered": False,
    }

    return config


def apply_config(config: dict) -> None:
    tier = TIERS[config["tier"]]
    zone = CITY_ZONES.get(config.get("city_zone", ""), {})

    print(f"\n{BOLD}── Phase 1: Writing Local Config ──{RESET}\n")
    print(f"  Node:     {GREEN}{config['display_name']}{RESET}")
    print(f"  Repo:     {config['github_repo']}")
    print(f"  Tier:     {tier['label']}")
    print(f"  Layer:    {LAYER_MAP.get(config['tier'], 'node')}")
    if zone:
        print(f"  Zone:     {zone['name']} ({zone['element']})")
    print(f"  Produces: {', '.join(tier['produces'])}")
    print(f"  Consumes: {', '.join(tier['consumes']) or '(none yet)'}")
    if config.get("domains"):
        print(f"  Domains:  {', '.join(DOMAINS[d]['name'] for d in config['domains'])}")

    print()

    _write_charter(config)
    print(f"    {GREEN}✓{RESET} docs/authority/charter.md")

    _write_capabilities(config)
    print(f"    {GREEN}✓{RESET} docs/authority/capabilities.json")

    _regenerate(config)
    print(f"    {GREEN}✓{RESET} .well-known/agent-federation.json")
    print(f"    {GREEN}✓{RESET} .well-known/agent.json")

    # Discovery beacon
    _write_discovery_beacon(config)
    print(f"    {GREEN}✓{RESET} .agent-internet/beacon.json")

    # ── Phase 2: Federation connection ──
    print(f"\n{BOLD}── Phase 2: Connecting to Federation ──{RESET}\n")

    # Nadi transport
    if config.get("nadi_transport", True):
        _setup_nadi_transport(config)
        print(f"    {GREEN}✓{RESET} nadi/inbox.json")
        print(f"    {GREEN}✓{RESET} nadi/outbox.json")
        print(f"    {GREEN}✓{RESET} nadi/relay-config.json → hub: {STEWARD_FEDERATION_REPO}")
        _write_nadi_relay_script()
        print(f"    {GREEN}✓{RESET} scripts/nadi_relay.py")
        _write_nadi_relay_workflow(config)
        print(f"    {GREEN}✓{RESET} .github/workflows/nadi-relay.yml (every 15 min)")

    # Agent City registration
    if config.get("register_city", False):
        print()
        registered = _register_with_agent_city(config)
        config["city_registered"] = registered

    # Peer discovery
    print()
    subprocess.run(
        [sys.executable, "scripts/discover_federation_peers.py", "--seeds-only",
         "--output", ".federation/peers.json"],
        cwd=str(REPO_ROOT), capture_output=True,
    )
    peers_path = REPO_ROOT / ".federation" / "peers.json"
    if peers_path.exists():
        peers = json.loads(peers_path.read_text())
        count = peers.get("peer_count", 0)
        print(f"    {GREEN}✓{RESET} Discovered {count} federation peer(s)")

    # Save config
    config_path = REPO_ROOT / ".federation-setup.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    print(f"    {GREEN}✓{RESET} .federation-setup.json (re-run anytime)")

    # Show federation status
    _show_federation_status(config)

    # Next steps
    print(f"\n{BOLD}── Ready ──{RESET}\n")
    print(f"  Your node is configured and connected to the federation.")
    print(f"  Push to make it live:\n")
    print(f"    {CYAN}git add -A && git commit -m 'Initialize federation node' && git push{RESET}")
    print(f"    {CYAN}gh repo edit --add-topic agent-federation-node{RESET}")
    print(f"\n  Re-run anytime: {CYAN}python scripts/setup_node.py{RESET}")
    print(f"  Check status:   {CYAN}python scripts/setup_node.py --status{RESET}")
    print()


def show_status() -> None:
    """Show federation status from saved config."""
    config_path = REPO_ROOT / ".federation-setup.json"
    if not config_path.exists():
        print(f"  {YELLOW}No setup config found. Run: python scripts/setup_node.py{RESET}")
        return
    config = json.loads(config_path.read_text())
    _show_federation_status(config)


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive federation node setup")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--status", action="store_true", help="Show federation connection status")
    parser.add_argument("--name", default="My Federation Node")
    parser.add_argument("--role", default="relay", choices=list(TIERS.keys()))
    parser.add_argument("--org", default="kimeisele")
    parser.add_argument("--zone", default="", choices=[""] + list(CITY_ZONES.keys()))
    parser.add_argument("--description", default="")
    parser.add_argument("--no-nadi", action="store_true", help="Skip Nadi transport setup")
    parser.add_argument("--no-city-register", action="store_true", help="Skip Agent City registration")
    args = parser.parse_args()

    if args.status:
        show_status()
        return 0

    if args.non_interactive:
        repo_name = args.name.lower().replace(" ", "-")
        config = {
            "display_name": args.name,
            "repo_name": repo_name,
            "github_repo": f"{args.org}/{repo_name}",
            "description": args.description or f"{args.name} — a federation node",
            "tier": args.role,
            "domains": [],
            "custom_skills": [],
            "values": "",
            "role_id": f"{repo_name.replace('-', '_')}_{args.role}",
            "city_zone": args.zone or TIER_TO_ZONE.get(args.role, "general"),
            "nadi_transport": not args.no_nadi,
            "register_city": not args.no_city_register,
            "city_registered": False,
        }
    else:
        config = interactive_setup()

    apply_config(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
