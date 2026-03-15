#!/usr/bin/env python3
"""Interactive federation node setup wizard.

Walks a new node owner through configuration — adapting to their role,
capabilities, and ambitions while always including the core federation
kernel (descriptor, authority feed, peer discovery).

Usage:
    python scripts/setup_node.py
    python scripts/setup_node.py --non-interactive --name "My Node" --role research
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

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


# ── File generators ───────────────────────────────────────────────────────


def _write_charter(config: dict) -> None:
    charter_path = REPO_ROOT / "docs" / "authority" / "charter.md"
    name = config["display_name"]
    description = config["description"]
    tier = TIERS[config["tier"]]

    lines = [
        f"# {name} Charter",
        "",
        f"> {description}",
        "",
        f"## Role",
        "",
        f"This node operates as a **{tier['label']}** in the agent-internet federation.",
        "",
    ]
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

    lines.append("## Federation Commitment")
    lines.append("")
    lines.append("This node commits to the federation's core principles:")
    lines.append("- Publish truthful, verifiable authority documents")
    lines.append("- Respect boundary separation (substrate / world / city / membrane)")
    lines.append("- Participate in peer review and trust verification")
    lines.append("")

    charter_path.write_text("\n".join(lines))


def _write_capabilities(config: dict) -> None:
    caps_path = REPO_ROOT / "docs" / "authority" / "capabilities.json"
    tier = TIERS[config["tier"]]

    skills = [{"id": cap, "name": cap.replace("-", " ").title(), "description": f"{cap.replace('-', ' ').title()} capability."} for cap in tier["capabilities"]]

    # Add custom skills
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

    if config.get("domains"):
        manifest["faculties"] = [DOMAINS[d] for d in config["domains"]]

    caps_path.write_text(json.dumps(manifest, indent=2) + "\n")


def _regenerate(config: dict) -> None:
    """Regenerate all auto-generated files."""
    repo = config.get("github_repo", f"kimeisele/{config['repo_name']}")
    layer = LAYER_MAP.get(config["tier"], "node")

    subprocess.run(
        [sys.executable, "scripts/render_federation_descriptor.py", "--repo", repo, "--layer", layer],
        cwd=str(REPO_ROOT),
        capture_output=True,
    )
    subprocess.run(
        [sys.executable, "scripts/render_agent_card.py", "--repo", repo],
        cwd=str(REPO_ROOT),
        capture_output=True,
    )


# ── Main wizard ───────────────────────────────────────────────────────────


def interactive_setup() -> dict:
    print(f"\n{BOLD}{'═' * 60}{RESET}")
    print(f"{BOLD}  Federation Node Setup Wizard{RESET}")
    print(f"{BOLD}{'═' * 60}{RESET}")
    print(f"\n  {DIM}Every node includes the core federation kernel:{RESET}")
    print(f"  {DIM}  descriptor + authority feed + peer discovery + A2A card{RESET}\n")

    # Identity
    print(f"{BOLD}── Identity ──{RESET}")
    display_name = _ask("Node name", "My Federation Node")
    repo_name = display_name.lower().replace(" ", "-")
    repo_name = _ask("Repository name", repo_name)
    github_org = _ask("GitHub org/user", "kimeisele")
    description = _ask("One-line description", f"{display_name} — a federation node")

    # Tier
    tier = _ask_choice(
        "What kind of node do you want to run?",
        {k: v["description"] for k, v in TIERS.items()},
        default="relay",
    )

    # Domains (for research/contributor)
    domains: list[str] = []
    if tier in ("research", "contributor"):
        domains = _ask_multi(
            "Which domains does your node cover?",
            {k: v["name"] for k, v in DOMAINS.items()},
        )

    # Custom capabilities
    custom_skills: list[str] = []
    if _ask_yn("Do you want to add custom capabilities beyond the defaults?", default=False):
        raw = _ask("List capabilities (comma-separated)", "")
        custom_skills = [s.strip() for s in raw.split(",") if s.strip()]

    # Values
    values = ""
    if _ask_yn("Would you like to add a values statement to your charter?", default=False):
        values = _ask("Your values (one paragraph)", "")

    # Role ID
    role_id = _ask("Node role identifier", f"{repo_name.replace('-', '_')}_{tier}")

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
    }

    return config


def apply_config(config: dict) -> None:
    tier = TIERS[config["tier"]]
    print(f"\n{BOLD}── Applying Configuration ──{RESET}\n")
    print(f"  Node:     {GREEN}{config['display_name']}{RESET}")
    print(f"  Repo:     {config['github_repo']}")
    print(f"  Tier:     {tier['label']}")
    print(f"  Layer:    {LAYER_MAP.get(config['tier'], 'node')}")
    print(f"  Produces: {', '.join(tier['produces'])}")
    print(f"  Consumes: {', '.join(tier['consumes']) or '(none)'}")
    if config.get("domains"):
        print(f"  Domains:  {', '.join(DOMAINS[d]['name'] for d in config['domains'])}")

    print(f"\n  {DIM}Writing files...{RESET}")

    _write_charter(config)
    print(f"    {GREEN}✓{RESET} docs/authority/charter.md")

    _write_capabilities(config)
    print(f"    {GREEN}✓{RESET} docs/authority/capabilities.json")

    _regenerate(config)
    print(f"    {GREEN}✓{RESET} .well-known/agent-federation.json")
    print(f"    {GREEN}✓{RESET} .well-known/agent.json")

    # Save setup config for reproducibility
    config_path = REPO_ROOT / ".federation-setup.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    print(f"    {GREEN}✓{RESET} .federation-setup.json (saved for re-runs)")

    # Run quickstart validation
    print(f"\n{BOLD}── Validating ──{RESET}\n")
    subprocess.run([sys.executable, "scripts/quickstart.py"], cwd=str(REPO_ROOT))

    print(f"\n{BOLD}── Next Steps ──{RESET}\n")
    print(f"  1. Review your charter:    {CYAN}docs/authority/charter.md{RESET}")
    print(f"  2. Push to GitHub:         {CYAN}git add -A && git commit -m 'Initialize federation node' && git push{RESET}")
    print(f"  3. Add the topic:          {CYAN}gh repo edit --add-topic agent-federation-node{RESET}")
    print(f"  4. Re-run setup anytime:   {CYAN}python scripts/setup_node.py{RESET}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive federation node setup")
    parser.add_argument("--non-interactive", action="store_true", help="Skip prompts, use defaults/flags")
    parser.add_argument("--name", default="My Federation Node")
    parser.add_argument("--role", default="relay", choices=list(TIERS.keys()))
    parser.add_argument("--org", default="kimeisele")
    parser.add_argument("--description", default="")
    args = parser.parse_args()

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
        }
    else:
        config = interactive_setup()

    apply_config(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
