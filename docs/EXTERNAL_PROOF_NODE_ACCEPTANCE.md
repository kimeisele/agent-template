# Gate 6 — External Proof Node Acceptance

> **Status:** IN PROGRESS  
> **Template:** `kimeisele/agent-template` @ `71da4c7b0cbca73d78ddeaee9ac68d11b6f15e34`  
> **Final Candidate:** `kimeisele/agent-template-acceptance-node-05`  
> **Node main SHA:** `bf4080022e5ee8b95330ecb89fe1568b8160735c`

## Offline Proofs — PASS

| Check | Result |
|-------|--------|
| Core `.[dev]` | 255 passed, 13 skipped, Exit 0 |
| Federation `.[dev,federation]` | 268 passed, Exit 0 |
| Display name | "Final Acceptance Node 05" (5/5 artifacts) |
| Machine identity | `repo_id` = `agent-template-acceptance-node-05` |
| Governance | `agent-federation-baseline-v1` ACTIVE, CONFORMANT |
| Direct push blocked | Yes — "Changes must be made through a pull request." |
| `.venv*` gitignore | Present |
| Inbox/outbox | Empty |
| `.node_keys.json` | Not present |

---

## Live Proofs

### 1. Secretless Workflow — PASS

| Field | Value |
|-------|-------|
| **Run ID** | `29848638989` |
| **SHA** | `bf4080022e5ee8b95330ecb89fe1568b8160735c` |
| **Conclusion** | **SUCCESS** |
| **Guard** | `REMOTE_DISABLED_MISSING_PAT` |
| **Relay** | All skipped, clear notice |
| **No `.node_keys.json`** | Confirmed |
| **No secret leakage** | Confirmed |

### 2. Invalid-Key — PASS

| Field | Value |
|-------|-------|
| **Run ID** | `29848940075` |
| **SHA** | `bf4080022e5ee8b95330ecb89fe1568b8160735c` |
| **Conclusion** | **FAILURE** (expected) |
| **Error** | `RuntimeError: No usable node identity: NODE_PRIVATE_KEY is unset or unparseable` |
| **Fallback** | None generated, no `.node_keys.json` |
| **No secret leakage** | Confirmed |

### 3. False-Success Guard — PASS

| Field | Value |
|-------|-------|
| **Run ID** | `29849222134` |
| **SHA** | `bf4080022e5ee8b95330ecb89fe1568b8160735c` |
| **Conclusion** | **FAILURE** |
| **Key load** | Yes — `loaded PEM-encoded secret from NODE_PRIVATE_KEY env` |
| **Messages** | 8 heartbeat + 1 federation.agent_claim signed |
| **Source** | `ag_ed8a1079acc8c9e6` |
| **Final sync** | `pulled=0, pushed=9, processed=0, expired=0, exit 0` |
| **Hub postcondition** | FAIL — `no hub files for source ag_ed8a1079acc8c9e6` |

**Architecture finding:** nadi-kit `pushed` counter and exit code are non-authoritative for remote persistence. The exact-message postcondition is the only reliable success indicator.

### 4. Run `29854586384` — Additional False-Success Confirmation

| Field | Value |
|-------|-------|
| **SHA** | `bf4080022e5ee8b95330ecb89fe1568b8160735c` |
| **Conclusion** | **FAILURE** |
| **Core** | SUCCESS |
| **Hub preflight** | SUCCESS |
| **Messages** | Signed and captured |
| **Final sync** | SUCCESS (exit 0) |
| **Postcondition** | FAIL — same source, no hub mailbox |

### 5. Restricted-PAT — BLOCKED_MANUAL_CREDENTIAL

Requires fine-grained PAT: Repository `kimeisele/steward-federation`, Contents: Read only.

### 6. Valid Remote Heartbeat E2E — BLOCKED_MANUAL_CREDENTIAL

Requires fine-grained PAT: Repository `kimeisele/steward-federation`, Contents: Read and Write.

---

## Full Workflow Inventory

### sync-agent-card.yml
| Field | Value |
|-------|-------|
| **Name** | Sync Agent Card |
| **Triggers** | `push` (main, paths-ignore `.well-known/**`), `workflow_dispatch` |
| **Dispatch** | Yes |
| **Permissions** | `contents: write` |
| **Secrets** | None (uses auto `GITHUB_TOKEN`) |
| **Reads** | Node repository |
| **Writes** | Node repository (`.well-known/agent.json`) |
| **Artifact** | `.well-known/agent.json` |
| **Identity** | `federation-bot` / `bot@federation` |
| **Run** | `29848524256` @ `bf4080022e5ee8b95330ecb89fe1568b8160735c` |
| **Conclusion** | SUCCESS |
| **Hardcoded template** | None |
| **No key file** | N/A |

### sync-federation-descriptor.yml
| Field | Value |
|-------|-------|
| **Name** | Sync Federation Descriptor |
| **Triggers** | `push` (main, paths-ignore `.well-known/**`), `workflow_dispatch` |
| **Dispatch** | Yes |
| **Permissions** | `contents: write` |
| **Secrets** | None (uses auto `GITHUB_TOKEN`) |
| **Reads** | Node repository |
| **Writes** | Node repository (`.well-known/agent-federation.json`) |
| **Artifact** | `.well-known/agent-federation.json` |
| **Identity** | `federation-bot` / `bot@federation` |
| **Run** | `29848524180` @ `bf4080022e5ee8b95330ecb89fe1568b8160735c` |
| **Conclusion** | SUCCESS |
| **Hardcoded template** | None |
| **No key file** | N/A |

### publish-authority-feed.yml
| Field | Value |
|-------|-------|
| **Name** | Publish Authority Feed |
| **Triggers** | `push` (main), `workflow_dispatch` |
| **Dispatch** | Yes |
| **Permissions** | `contents: write` |
| **Secrets** | None |
| **Reads** | Node repository |
| **Writes** | `authority-feed` branch via reusable workflow |
| **Artifact** | `latest-authority-manifest.json` on `authority-feed` branch |
| **Run** | `29848524726` @ `bf4080022e5ee8b95330ecb89fe1568b8160735c` |
| **Conclusion** | SUCCESS |
| **Hardcoded template** | None (reusable workflow from `kimeisele/agent-internet`) |
| **No key file** | N/A |

### heartbeat.yml
| Field | Value |
|-------|-------|
| **Name** | Node Heartbeat |
| **Triggers** | `workflow_dispatch`, `schedule` (`*/15 * * * *`) |
| **Dispatch** | Yes |
| **Permissions** | `contents: read` |
| **Required Secrets** | `FEDERATION_PAT` (optional), `NODE_PRIVATE_KEY` (optional) |
| **Reads** | Node repository, Hub (`kimeisele/steward-federation`) via `gh api` |
| **Writes** | Hub (`kimeisele/steward-federation`) via nadi-kit relay |
| **Artifact** | Captured heartbeat proof (`heartbeat-proof.json`, ephemeral) |
| **Postcondition** | Exact message ID in hub mailbox via `heartbeat_postcondition.py verify` |
| **Identity** | Dynamic — from materialized `peer.json` crypto source |
| **Run** | `29854586384` @ `bf4080022e5ee8b95330ecb89fe1568b8160735c` |
| **Conclusion** | FAILURE (no write PAT — expected) |
| **Hardcoded template** | None |
| **No key file** | Confirmed — no `.node_keys.json` generation |

### federation-discovery.yml
| Field | Value |
|-------|-------|
| **Name** | Federation Discovery |
| **Triggers** | `schedule` (`0 6 * * 1` — weekly Monday 06:00 UTC), `workflow_dispatch` |
| **Dispatch** | Yes |
| **Permissions** | `contents: write` |
| **Secrets** | None (uses auto `GITHUB_TOKEN`) |
| **Reads** | GitHub API topic search, peer `.well-known/agent-federation.json` |
| **Writes** | Node repository (`.federation/peers.json`) |
| **Artifact** | `.federation/peers.json` |
| **Identity** | `federation-bot` / `bot@federation` |
| **Status** | **INVENTORIED — EXECUTION PENDING SCHEDULE** (safe to run via `workflow_dispatch`) |
| **Hardcoded template** | None |

---

## Permission Matrix

| Workflow | `contents` | Secrets | Write Target |
|----------|-----------|---------|-------------|
| sync-agent-card | `write` | auto `GITHUB_TOKEN` | Node repo `.well-known/agent.json` |
| sync-federation-descriptor | `write` | auto `GITHUB_TOKEN` | Node repo `.well-known/agent-federation.json` |
| publish-authority-feed | `write` | auto `GITHUB_TOKEN` | Node repo `authority-feed` branch |
| heartbeat | `read` | `FEDERATION_PAT`, `NODE_PRIVATE_KEY` (optional) | Hub repo via nadi-kit |
| federation-discovery | `write` | auto `GITHUB_TOKEN` | Node repo `.federation/peers.json` |

---

## Security Verification

| Check | All Workflows |
|-------|--------------|
| No hardcoded `agent-template` identity | ✅ |
| No private key written to artifacts | ✅ |
| No automatic `.node_keys.json` generation | ✅ |
| No direct push to protected `main` | ✅ (governance active) |
| No excessive `GITHUB_TOKEN` permissions | ✅ |
| No secret values printed | ✅ |
| Remote writes have postcondition | ✅ (`heartbeat_postcondition.py verify`) |
| No `pull_request_target` | ✅ |

---

## Acceptance Matrix

| AT-REC | Finding | Gate | Status |
|--------|---------|------|--------|
| AT-REC-001 | NADI outbox path | 3 | PASS |
| AT-REC-002 | Renderer fallback | 1 | PASS |
| AT-REC-003 | Topic destructive | 4 | PASS |
| AT-REC-004 | Package identity | 1 | PASS |
| AT-REC-005 | Dev dependencies | 2 | PASS |
| AT-REC-006 | Non-interactive guess | 1 | PASS |
| AT-REC-007 | Workflow hardcoded | 5 | PASS |
| AT-REC-008 | Push-to-main | 5 | PASS |
| AT-REC-009 | Static test counts | 5 | PASS |
| AT-REC-010 | Test identity | 1 | PASS |
| AT-REC-011 | Install contract | 2 | PASS |
| AT-REC-012 | NADI runtime | 2 | PASS |
| AT-REC-013 | Postcondition | 4 | PASS |
| AT-REC-014 | Workflow secrets | 5 | PASS |
| AT-REC-015 | Product claims | 5 | PASS |
| AT-REC-016 | Package discovery | 1-2 | PASS |
| AT-REC-017 | NADI docs | 3 | PASS |

---

## Superseded Candidates

| Node | Disposition |
|------|------------|
| 01 | Diagnostic (manual fixes) |
| 02 | Intermediate |
| 03 | `.venv*` gitignore missing |
| 04 | Ruff fix direct-pushed, governance absent |

## Template Fixes Produced (Gate 6)

| PR | Description |
|----|-------------|
| #17 | Display name from committed capabilities.json |
| #18 | Core profile NADI test skip |
| #19 | Defensive `_check_topic()` |
| #20 | `.venv*` gitignore |
| #21 | Ruff CI fixes |
