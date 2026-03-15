# agent-template

Use this repository as a GitHub template for a new federation node.

## What you get

- `.well-known/agent-federation.json` descriptor
- `.well-known/agent.json` — A2A-compatible Agent Card for capability discovery
- automatic descriptor & agent card sync workflows
- reusable authority-feed publish workflow
- **federation peer discovery** — find other nodes via the GitHub API
- **peer authority verification** — fetch and SHA-256-verify peer feeds
- scheduled discovery workflow (weekly)
- minimal example authority export script

## Quick start

1. Click **Use this template** on GitHub.
2. Give the new repository the topic `agent-federation-node`.
3. Push your own authority documents into `docs/authority/`.
4. Optionally edit `docs/authority/capabilities.json` to declare your node's skills.
5. Trigger `Publish Authority Feed` or push to `main`.

The template will:

- regenerate `.well-known/agent-federation.json`
- regenerate `.well-known/agent.json` (A2A Agent Card)
- publish `authority-feed/latest-authority-manifest.json`
- become discoverable by `agent-internet`

## Federation discovery

Discover peer nodes in the federation:

```bash
# discover all repos with the agent-federation-node topic
python scripts/discover_federation_peers.py

# limit to a specific org
python scripts/discover_federation_peers.py --org kimeisele

# fetch and verify a peer's authority feed
python scripts/fetch_peer_authority.py <manifest-url>

# fetch all peer feeds from a discovered registry
python scripts/fetch_peer_authority.py --peers .federation/peers.json
```

The `Federation Discovery` workflow runs weekly and commits the results to
`.federation/peers.json`, giving your node an up-to-date view of the network.

## A2A Agent Card

Each node publishes an [A2A-compatible](https://a2aprotocol.ai/) Agent Card at
`.well-known/agent.json`. The card is auto-generated from the federation
descriptor and `docs/authority/capabilities.json`. Other agents and
orchestration platforms can fetch this card to discover your node's skills.

## Default files

| File | Purpose |
|------|---------|
| `docs/authority/charter.md` | canonical authority document |
| `docs/authority/capabilities.json` | node skill & protocol declarations |
| `.well-known/agent-federation.json` | federation descriptor (auto-generated) |
| `.well-known/agent.json` | A2A Agent Card (auto-generated) |
| `scripts/render_federation_descriptor.py` | writes the well-known descriptor |
| `scripts/render_agent_card.py` | writes the A2A Agent Card |
| `scripts/export_authority_feed.py` | writes a valid authority feed bundle |
| `scripts/discover_federation_peers.py` | discovers peers via GitHub API |
| `scripts/fetch_peer_authority.py` | fetches & verifies peer authority feeds |

Replace the example content, keep the workflow wiring, and you have a live node.
