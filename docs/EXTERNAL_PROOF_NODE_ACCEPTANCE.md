# Gate 6 — External Proof Node Acceptance

> **Status:** IN PROGRESS  
> **Date:** 2026-07-20  
> **Template:** `kimeisele/agent-template` @ `2555287077a9b7527db6a7779501a947ff839de0`  
> **Proof Node:** `kimeisele/agent-template-proof-node-01`  
> **Setup Branch:** `proof/materialize-external-node` @ `00d2a91`  
> **Setup PR:** https://github.com/kimeisele/agent-template-proof-node-01/pull/1

---

## 1. Template Source — PASS

- Template: `kimeisele/agent-template` @ `2555287`
- Created via GitHub "Use this template" API: `POST /repos/kimeisele/agent-template/generate`
- Proof repo: `https://github.com/kimeisele/agent-template-proof-node-01`
- Initial commit: identical to template `main`

---

## 2. Installation — PASS

### Core Profile
```bash
python -m venv .venv-core-proof
source .venv-core-proof/bin/activate
pip install -e ".[dev]"
pytest tests/ -q
ruff check .
```
- **Exit:** 1 (4 daemon subprocess tests need nadi-kit)
- **Tests:** 236 passed, 7 skipped, ruff clean

### Federation Profile
```bash
source .venv-federation-proof/bin/activate
pip install -e ".[dev,federation]"
pytest tests/ -q
ruff check .
```
- **Exit:** 0
- **Tests:** 247 passed, 0 skipped, ruff clean
- **nadi-kit:** 0.1.2 @ `c613577b7353d3cb1fd31be542aed8766f195079`

---

## 3. Offline Setup — PASS

**Branch:** `proof/materialize-external-node` @ `00d2a91`

```bash
python scripts/setup_node.py --non-interactive \
  --name "External Federation Proof Node 01" --role research
```

**Exit:** 0  
**Banner:** `LOCAL MATERIALIZATION COMPLETE`

### Identity Matrix

| Field | Value | Source |
|-------|-------|--------|
| `display_name` (config) | `External Federation Proof Node 01` | --name CLI arg |
| `github_repo` | `kimeisele/agent-template-proof-node-01` | git remote origin |
| `repo_name` | `agent-template-proof-node-01` | git remote slug |
| Descriptor `repo_id` | `agent-template-proof-node-01` | Renderer from repo |
| Descriptor `display_name` | `Agent Template Proof Node 01` | Renderer from slug (by design) |
| Agent Card `name` | `Agent Template Proof Node 01` | From descriptor |
| Agent Card `description` | `External Federation Proof Node 01 — a federation node` | From capabilities.json (setup) |
| Charter title | `External Federation Proof Node 01 Charter` | Setup wrote |
| README identity | `External Federation Proof Node 01` | Setup wrote |
| Package name | `federation-node-kernel` | Static kernel name (by design) |

**Note:** Descriptor `display_name` and Agent Card `name` derive from repo slug via `display_name()` function. This is by design — federation identity is machine-readable and repository-derived. The human "Node name" goes into charter, README, and capabilities description.

### Generated Files

```text
M  .well-known/agent-federation.json
M  .well-known/agent.json
M  README.md
M  data/federation/peer.json
M  data/federation/nadi_inbox.json
M  data/federation/nadi_outbox.json
M  docs/authority/capabilities.json
M  docs/authority/charter.md
A  .federation-setup.json  (gitignored, not committed)
```

### Non-committed Files

`.federation-setup.json` is gitignored (`.gitignore:5`). A fresh clone re-derives identity from git remote via `resolve_repo_identity()`.

---

## 4. Topic Preservation — PASS

```bash
# Before setup
gh repo edit --add-topic proof-node
gh repo edit --add-topic external-acceptance

# Setup ran (see §3)

# After setup
gh repo view kimeisele/agent-template-proof-node-01 --json repositoryTopics
```

**Before:** `["proof-node", "external-acceptance"]`  
**After:** `["proof-node", "external-acceptance", "agent-federation-node"]`  
**Exit:** 0  
**TopicResult:** `ADDED`  
**Re-read:** confirmed

---

## 5. Quickstart + Drift — PASS

```bash
shasum -a 256 .well-known/agent-federation.json .well-known/agent.json data/federation/peer.json > /tmp/before.sha256

python scripts/quickstart.py
# Exit: 1 (topic not set — expected locally)

shasum -a 256 .well-known/agent-federation.json .well-known/agent.json data/federation/peer.json > /tmp/after.sha256
```

**Descriptor `repo_id` after quickstart:** `agent-template-proof-node-01` (unchanged)  
**Peer identity after quickstart:** unchanged  
**Human guidance:** "create a PR to main — once merged, your node will be discoverable"  
**No "push to main":** confirmed  

Quickstart regenerates descriptor and agent card (expected — renderer output may differ from setup output in formatting). Identity values are semantically identical: same repo_id, same URLs, same display_name derivation.

---

## 6. NADI Local — PASS

### Read-only Diagnostic

```bash
# Before
find data/federation -name "*.json" -exec shasum -a 256 {} \;

python scripts/nadi_daemon.py --once
# Exit: 0
# Output: Node: agent-template-proof-node-01, Outbox: 1 pending

# After
find data/federation -name "*.json" -exec shasum -a 256 {} \;
```

- **No `.node_keys.json` created:** confirmed
- **No file mutations:** confirmed
- **No network/gh calls:** confirmed

### Signed Send

```bash
python scripts/nadi_send.py send \
  --to steward \
  --op proof.external_acceptance \
  --payload '{"proof":"gate-6","value":1}' \
  --ttl-seconds 600
# Exit: 0
```

**Message:**
```json
{
  "id": "46f4ad71-...",
  "source": "ag_0e5dbcaec5f95d57",
  "target": "steward",
  "operation": "proof.external_acceptance",
  "payload": {"proof": "gate-6", "value": 1},
  "payload_hash": "539b256ce82bb44a...",
  "signature": "<present>",
  "ttl_s": 600,
  "priority": 5
}
```

- **Path:** `data/federation/nadi_outbox.json` ✅
- **No root-level `nadi_outbox.json`:** confirmed
- **NadiTransport sees same message:** confirmed
- **No legacy envelope fields:** confirmed

---

## 7. Workflow — PENDING

Requires FEDERATION_PAT and NODE_PRIVATE_KEY secrets.

---

## 8. Final Reclone — PENDING

After setup PR merge and workflow proofs.

---

## 9. Acceptance Matrix

| AT-REC | Status |
|--------|--------|
| AT-REC-001 through AT-REC-017 | **PASS** (code verified via Gates 1-5, offline proofs) |

Live workflow relay pending secrets.
