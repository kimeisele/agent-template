# Gate 6 — External Proof Node Acceptance

> **Status:** IN PROGRESS  
> **Template:** `kimeisele/agent-template` @ `71da4c7` (post PR #17–#21)  
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

## Live Proofs

### 1. Secretless Workflow — PASS

| Field | Value |
|-------|-------|
| **Run ID** | `29848638989` |
| **SHA** | `bf40800` |
| **Conclusion** | **SUCCESS** |
| **Guard** | `REMOTE_DISABLED_MISSING_PAT` |
| **Relay** | All skipped, clear notice |

### 2. Invalid-Key — PASS

| Field | Value |
|-------|-------|
| **Run ID** | `29848940075` |
| **SHA** | `bf40800` |
| **Conclusion** | **FAILURE** (expected) |
| **Error** | `RuntimeError: No usable node identity: NODE_PRIVATE_KEY is unset or unparseable` |
| **Fallback** | None generated, no `.node_keys.json` |

### 3. False-Success Guard — PASS

| Field | Value |
|-------|-------|
| **Run ID** | `29849222134` |
| **SHA** | `bf40800` |
| **Conclusion** | **FAILURE** |
| **Key load** | Yes — `loaded PEM-encoded secret from NODE_PRIVATE_KEY env` |
| **Messages** | 8 heartbeat + 1 federation.agent_claim signed |
| **Source** | `ag_ed8a1079acc8c9e6` |
| **Final sync** | `pushed=9, exit 0` |
| **Hub postcondition** | FAIL — `no hub files for source ag_ed8a1079acc8c9e6` |

**Architecture finding:** nadi-kit `pushed` counter and exit code are non-authoritative for remote persistence. The exact-message postcondition is the only reliable success indicator.

### 4. Restricted-PAT — BLOCKED_MANUAL_CREDENTIAL

Requires fine-grained PAT: Repository `kimeisele/steward-federation`, Contents: Read only.

### 5. Valid Remote Heartbeat E2E — BLOCKED_MANUAL_CREDENTIAL

Requires fine-grained PAT: Repository `kimeisele/steward-federation`, Contents: Read and Write.

## Workflow Inventory

| Workflow | Latest Run | SHA | Conclusion |
|----------|-----------|-----|------------|
| `sync-agent-card.yml` | `29848524256` | `bf40800` | SUCCESS |
| `sync-federation-descriptor.yml` | `29848524180` | `bf40800` | SUCCESS |
| `publish-authority-feed.yml` | `29848524726` | `bf40800` | SUCCESS |
| `heartbeat.yml` | `29854586384` | `bf40800` | FAILURE (no write PAT) |
| `federation-discovery.yml` | scheduled weekly | — | PENDING |

## Final Reclone — PENDING

After valid heartbeat E2E PASS.

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
