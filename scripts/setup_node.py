#!/usr/bin/env python3
"""Interactive federation node setup wizard.

Two phases:
  Phase 1 — Identity: configure your node locally (charter, capabilities, descriptors)
  Phase 2 — Connect: choose your Agent City zone, discover peers, verify readiness

Branch governance is evaluated after the two phases.  Apply with
``--apply-governance`` or interactively.

Usage:
    python scripts/setup_node.py
    python scripts/setup_node.py --non-interactive --name "My Node" --role research
    python scripts/setup_node.py --status
    python scripts/setup_node.py --apply-governance
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Add scripts/ to path so governance can import federation_utils
_SCRIPTS = str(Path(__file__).resolve().parent)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from governance._models import (  # noqa: E402
    BypassState,
    ComplianceStatus,
    Diagnostic,
    GovernanceCheck,
)
from governance._protection import ensure_governance_baseline, inspect_governance  # noqa: E402
from governance._repo import detect_repository  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]

GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# ── Federation constants ──────────────────────────────────────────────────

AGENT_CITY_REPO = "kimeisele/agent-city"

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


# ── File generators ───────────────────────────────────────────────────────


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
        lines.extend(["## Domains", ""])
        for d in config["domains"]:
            lines.append(f"- **{DOMAINS[d]['name']}**")
        lines.append("")

    if config.get("values"):
        lines.extend(["## Values", "", config["values"], ""])

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
        }

    if config.get("domains"):
        manifest["faculties"] = [DOMAINS[d] for d in config["domains"]]

    caps_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def _write_peer_json(config: dict) -> None:
    """Write NADI peer descriptor with the configured node identity."""
    peer_dir = REPO_ROOT / "data" / "federation"
    peer_dir.mkdir(parents=True, exist_ok=True)
    peer_path = peer_dir / "peer.json"

    repo = config.get("github_repo", f"kimeisele/{config['repo_name']}")
    node_id = config["repo_name"]
    tier = TIERS[config["tier"]]

    peer_data = {
        "identity": {
            "city_id": node_id,
            "slug": node_id,
            "repo": repo,
            "public_key": "",
        },
        "endpoint": {
            "city_id": node_id,
            "transport": "filesystem",
            "location": "data/federation",
        },
        "capabilities": tier["capabilities"],
        "nadi": {
            "outbox": "data/federation/nadi_outbox.json",
            "inbox": "data/federation/nadi_inbox.json",
            "reports": "data/federation/reports/",
            "directives": "data/federation/directives/",
        },
    }

    peer_path.write_text(json.dumps(peer_data, indent=2) + "\n")

    # Ensure inbox/outbox exist
    for fname in ("nadi_inbox.json", "nadi_outbox.json"):
        fpath = peer_dir / fname
        if not fpath.exists() or fpath.read_text().strip() == "":
            fpath.write_text("[]\n")

    # Ensure subdirectories exist
    (peer_dir / "reports").mkdir(exist_ok=True)
    (peer_dir / "directives").mkdir(exist_ok=True)


def _regenerate(config: dict) -> None:
    repo = config.get("github_repo", f"kimeisele/{config['repo_name']}")
    layer = LAYER_MAP.get(config["tier"], "node")
    for script, extra_args in [
        ("render_federation_descriptor.py", ["--repo", repo, "--layer", layer]),
        ("render_agent_card.py", ["--repo", repo]),
    ]:
        result = subprocess.run(
            [sys.executable, f"scripts/{script}", *extra_args],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"    {YELLOW}warning: {script} failed: {result.stderr.strip()[:80]}{RESET}")


def _set_federation_topic(repo_full_name: str) -> bool:
    """Set the ``agent-federation-node`` topic on *repo_full_name*.

    Tries ``gh`` CLI first, then falls back to ``GITHUB_TOKEN`` /
    ``GH_TOKEN`` environment variables with ``curl``.

    Returns ``True`` if the topic was applied successfully.
    """
    TOPIC = "agent-federation-node"

    # 1. Try gh CLI
    try:
        result = subprocess.run(
            ["gh", "repo", "edit", repo_full_name, "--add-topic", TOPIC],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 2. Try GITHUB_TOKEN / GH_TOKEN env var via curl
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        try:
            result = subprocess.run(
                [
                    "curl", "-sf", "-X", "PUT",
                    f"https://api.github.com/repos/{repo_full_name}/topics",
                    "-H", "Accept: application/vnd.github+json",
                    "-H", f"Authorization: token {token}",
                    "-H", "Content-Type: application/json",
                    "-d", f'{{"names":["{TOPIC}"]}}',
                ],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    return False


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

    return {
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
    }


def apply_config(config: dict, *, interactive: bool, apply_governance: bool) -> int:
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

    # ── Phase 2: Federation connection ──
    print(f"\n{BOLD}── Phase 2: Connecting to Federation ──{RESET}\n")

    # NADI peer descriptor + inbox/outbox
    _write_peer_json(config)
    print(f"    {GREEN}✓{RESET} data/federation/peer.json (NADI identity)")
    print(f"    {GREEN}✓{RESET} data/federation/nadi_inbox.json")
    print(f"    {GREEN}✓{RESET} data/federation/nadi_outbox.json")

    # Peer discovery
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
            print(f"    {GREEN}✓{RESET} Discovered {count} federation peer(s)")
            for peer in peers.get("peers", [])[:5]:
                desc = peer.get("federation_descriptor", {})
                name = desc.get("display_name", peer.get("full_name", "?"))
                print(f"      · {name}")
            if count > 5:
                print(f"      … and {count - 5} more")
    else:
        print(f"    {YELLOW}Could not reach peers (offline?){RESET}")

    # Save config
    config_path = REPO_ROOT / ".federation-setup.json"
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    print(f"    {GREEN}✓{RESET} .federation-setup.json (re-run anytime)")

    # Agent City registration guidance
    print(f"\n{BOLD}── Agent City Registration ──{RESET}\n")
    if zone:
        print(f"  Your node belongs in the {GREEN}{zone['name']}{RESET} zone ({zone['element']}).")
    print("  Register manually when ready:")
    print(f"    {CYAN}https://github.com/{AGENT_CITY_REPO}/issues/new?template=agent-registration.yml{RESET}")

    # Federation topic
    topic_ok = _set_federation_topic(config["github_repo"])

    # ── Governance: branch protection baseline ──
    governance_exit = _run_governance_step(interactive=interactive, apply_governance=apply_governance)

    # Next steps
    print(f"\n{BOLD}── Next Steps ──{RESET}\n")
    print(f"  1. Review your charter:  {CYAN}docs/authority/charter.md{RESET}")
    print(f"  2. Create setup branch:  {CYAN}git checkout -b setup-federation-node{RESET}")
    print(f"  3. Commit files:         {CYAN}git add -A && git commit -m 'Initialize federation node'{RESET}")
    print(f"  4. Push branch:          {CYAN}git push -u origin setup-federation-node{RESET}")
    print(f"  5. Open Pull Request:    {CYAN}(PR from setup-federation-node → main){RESET}")
    if topic_ok:
        print(f"  6. Topic:                {GREEN}agent-federation-node ✓{RESET}")
    else:
        print(f"  6. Add the topic:        {CYAN}gh repo edit --add-topic agent-federation-node{RESET}")
    print(f"  7. Register with city:   {CYAN}(link above){RESET}")
    print("  8. Review + merge PR")
    print(f"  9. Start NADI daemon:    {CYAN}python scripts/nadi_daemon.py --once{RESET}")
    print(f" 10. Send a message:       {CYAN}python scripts/nadi_send.py --to agent-internet --op heartbeat{RESET}")
    print(f"\n  Re-run: {CYAN}python scripts/setup_node.py{RESET}  |  Status: {CYAN}python scripts/setup_node.py --status{RESET}")
    print(f"  Apply governance: {CYAN}python scripts/setup_node.py --apply-governance{RESET}")
    print()
    return governance_exit


def _run_governance_step(*, interactive: bool, apply_governance: bool) -> ComplianceStatus:
    """Run the governance inspection and optionally apply the baseline.

    *interactive* controls whether the user may be prompted (``_ask_yn``).
    When ``False`` no stdin read occurs; the step is strictly non-blocking.

    *apply_governance* controls whether a write (POST) may be issued.
    When ``False`` the step is strictly read-only.

    Remote writes are ONLY allowed when:
      - ``apply_governance`` is ``True`` explicitly, OR
      - ``interactive`` is ``True`` AND the user confirms via ``_ask_yn``.

    Returns the final ComplianceStatus for exit-code decisions.
    """
    print(f"\n{BOLD}── Governance: Branch Protection Baseline ──{RESET}\n")

    repo, diag = detect_repository(REPO_ROOT)
    if repo is None:
        _print_governance_diag(diag)
        return ComplianceStatus.UNKNOWN

    print(f"  Repository:     {repo.full_name}")
    print(f"  Default Branch: {repo.default_branch}")

    check = inspect_governance(repo)
    _print_governance_check(check)

    if check.compliance == ComplianceStatus.CONFORMANT:
        return ComplianceStatus.CONFORMANT

    # Determine whether we are allowed to write
    may_write = apply_governance

    if not may_write and interactive and check.compliance == ComplianceStatus.NON_CONFORMANT:
        # Interactive mode: ask user before writing
        print("\n  The federation-baseline ruleset is not yet active on this repository.")
        if _ask_yn("  Create the 'agent-federation-baseline-v1' ruleset now?", default=True):
            may_write = True
        else:
            print(f"\n  {YELLOW}Skipped. Run with --apply-governance to set up later.{RESET}")

    if not may_write:
        if check.compliance == ComplianceStatus.NON_CONFORMANT and not interactive:
            print(f"\n  {YELLOW}Run with --apply-governance to set up branch protection.{RESET}")
        return check.compliance

    # Apply governance (only reached if may_write is True)
    print("\n  Applying federation-baseline ruleset...")
    result = ensure_governance_baseline(repo, check)
    print(f"  Action: {GREEN}{result.action or 'none'}{RESET}")

    # Display apply-step diagnostics
    for d in result.diagnostics:
        print(f"  {YELLOW}Diagnostic: {d.value}{RESET}")
    for detail in result.details:
        print(f"  {DIM}{detail}{RESET}")

    if result.final_check is not None:
        print()
        _print_governance_check(result.final_check)
        return result.final_check.compliance

    # No final_check → action failed completely
    print(f"\n  {YELLOW}Could not apply baseline.{RESET}")
    return ComplianceStatus.UNKNOWN


def _print_governance_check(check: GovernanceCheck) -> None:
    """Display a GovernanceCheck result to the user."""
    status_map = {
        ComplianceStatus.CONFORMANT: f"{GREEN}conformant{RESET}",
        ComplianceStatus.NON_CONFORMANT: f"{YELLOW}non-conformant{RESET}",
        ComplianceStatus.UNKNOWN: f"{YELLOW}unknown{RESET}",
    }
    print(f"  Compliance:      {status_map[check.compliance]}")

    if check.present_rules:
        print(f"  Present rules:   {', '.join(check.present_rules)}")
    if check.missing_rules:
        print(f"  Missing rules:   {YELLOW}{', '.join(check.missing_rules)}{RESET}")
    if check.unknown_rules:
        print(f"  Unknown rules:   {YELLOW}{', '.join(check.unknown_rules)}{RESET}")

    bypass_map = {
        BypassState.NONE_CONFIRMED: f"{GREEN}none confirmed{RESET}",
        BypassState.PRESENT: f"{YELLOW}present{RESET}",
        BypassState.UNKNOWN: f"{YELLOW}unknown{RESET}",
    }
    print(f"  Bypass actors:   {bypass_map[check.bypass_state]}")

    for detail in check.details:
        print(f"  {DIM}{detail}{RESET}")

    for d in check.diagnostics:
        print(f"  {YELLOW}Diagnostic: {d.value}{RESET}")


def _print_governance_diag(diag: Diagnostic) -> None:
    """Display a repository-detection diagnostic."""
    messages = {
        Diagnostic.REPO_NOT_FOUND: "No GitHub repository detected from git remote.",
        Diagnostic.AUTH_MISSING: "GitHub authentication missing. Set GITHUB_TOKEN, GH_TOKEN, or run 'gh auth login'.",
        Diagnostic.GITHUB_UNREACHABLE: "Could not reach GitHub API. Check network connectivity.",
    }
    msg = messages.get(diag, f"Could not evaluate governance: {diag.value}")
    print(f"  {YELLOW}{msg}{RESET}")


def show_status() -> ComplianceStatus | None:
    """Show federation status from saved config.

    Returns the governance ComplianceStatus for exit-code decisions,
    or ``None`` if no setup config exists.
    """
    config_path = REPO_ROOT / ".federation-setup.json"
    if not config_path.exists():
        print(f"  {YELLOW}No setup config found. Run: python scripts/setup_node.py{RESET}")
        return None

    config = json.loads(config_path.read_text())

    print(f"\n{BOLD}── Federation Status ──{RESET}\n")
    print(f"  Node:  {GREEN}{config.get('display_name', '?')}{RESET}")
    print(f"  Tier:  {TIERS.get(config.get('tier', ''), {}).get('label', '?')}")

    zone = CITY_ZONES.get(config.get("city_zone", ""), {})
    if zone:
        print(f"  Zone:  {zone['name']} ({zone['element']})")

    # Peer check
    _ = subprocess.run(
        [sys.executable, "scripts/discover_federation_peers.py", "--seeds-only",
         "--output", ".federation/peers.json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    peers_path = REPO_ROOT / ".federation" / "peers.json"
    if peers_path.exists():
        peers = json.loads(peers_path.read_text())
        count = peers.get("peer_count", 0)
        print(f"  Peers: {GREEN}{count} reachable{RESET}")

    # Governance status
    print(f"\n{BOLD}── Governance: Branch Protection ──{RESET}\n")
    repo, diag = detect_repository(REPO_ROOT)
    if repo is None:
        _print_governance_diag(diag)
        print()
        return ComplianceStatus.UNKNOWN

    print(f"  Repository:     {repo.full_name}")
    print(f"  Default Branch: {repo.default_branch}")
    check = inspect_governance(repo)
    _print_governance_check(check)

    print()
    return check.compliance


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive federation node setup")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--status", action="store_true", help="Show federation and governance status")
    parser.add_argument("--apply-governance", action="store_true",
                        help="Apply federation branch-protection baseline (can be used alone or with --non-interactive)")
    parser.add_argument("--name", default="My Federation Node")
    parser.add_argument("--role", default="relay", choices=list(TIERS.keys()))
    parser.add_argument("--org", default="kimeisele")
    parser.add_argument("--zone", default="", choices=[""] + list(CITY_ZONES.keys()))
    parser.add_argument("--description", default="")
    args = parser.parse_args()

    # ── --status: read-only inspection ──
    if args.status:
        status = show_status()
        if status is None:
            return 2  # no config
        if status == ComplianceStatus.CONFORMANT:
            return 0
        if status == ComplianceStatus.NON_CONFORMANT:
            return 1
        return 2  # UNKNOWN

    # ── --apply-governance alone: targeted governance run ──
    if args.apply_governance and not args.non_interactive and not any([
        args.name != "My Federation Node", args.role != "relay",
        args.org != "kimeisele", args.zone != "", args.description != "",
    ]):
        # Standalone governance run — load repo info from saved config
        return _run_governance_standalone()

    # ── Normal setup flow ──
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
        }
    else:
        config = interactive_setup()

    governance_exit = apply_config(config, interactive=not args.non_interactive, apply_governance=args.apply_governance)
    if args.apply_governance:
        # With explicit --apply-governance, exit code reflects governance result
        return governance_exit
    return 0


def _run_governance_standalone() -> int:
    """Run only the governance step (--apply-governance without setup).

    Reads repository information from .federation-setup.json.
    """
    config_path = REPO_ROOT / ".federation-setup.json"
    if not config_path.exists():
        print(f"  {YELLOW}No setup config found. Run: python scripts/setup_node.py{RESET}")
        return 2
    _ = json.loads(config_path.read_text())
    repo, diag = detect_repository(REPO_ROOT)
    if repo is None:
        _print_governance_diag(diag)
        return 2
    print(f"\n{BOLD}── Governance: Branch Protection Baseline ──{RESET}\n")
    print(f"  Repository:     {repo.full_name}")
    print(f"  Default Branch: {repo.default_branch}")
    check = inspect_governance(repo)
    _print_governance_check(check)
    if check.compliance == ComplianceStatus.CONFORMANT:
        print(f"\n  {GREEN}Already conformant — nothing to do.{RESET}")
        return 0
    print("\n  Applying federation-baseline ruleset...")
    result = ensure_governance_baseline(repo, check)
    print(f"  Action: {GREEN}{result.action or 'none'}{RESET}")

    # Display apply-step diagnostics
    for d in result.diagnostics:
        print(f"  {YELLOW}Diagnostic: {d.value}{RESET}")
    for detail in result.details:
        print(f"  {DIM}{detail}{RESET}")

    if result.final_check is not None:
        print()
        _print_governance_check(result.final_check)
        if result.final_check.compliance == ComplianceStatus.CONFORMANT:
            print(f"\n  {GREEN}Governance baseline applied successfully.{RESET}")
            return 0
        if result.final_check.compliance == ComplianceStatus.NON_CONFORMANT:
            print(f"\n  {YELLOW}Re-read did not confirm compliance.{RESET}")
            return 1
        print(f"\n  {YELLOW}Re-read returned unknown compliance.{RESET}")
        return 2

    # No final_check → action failed completely
    print(f"\n  {YELLOW}Could not apply baseline.{RESET}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
