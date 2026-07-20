# Gate 6 — External Proof Node Acceptance

> **Status:** IN PROGRESS  
> **Date:** 2026-07-20  
> **Template:** `kimeisele/agent-template` @ `2555287077a9b7527db6a7779501a947ff839de0`  
> **Proof Node:** `kimeisele/agent-template-proof-node-01`  
> **Setup PR:** https://github.com/kimeisele/agent-template-proof-node-01/pull/1

## Installation Proofs — PASS

| Profile | Result |
|---------|--------|
| Core `.[dev]` | 236 passed, 7 skipped, ruff clean |
| Federation `.[dev,federation]` | **247 passed**, nadi-kit 0.1.2 (pinned), ruff clean |

## Offline Setup — PASS

- `display_name`: External Federation Proof Node 01
- `github_repo`: kimeisele/agent-template-proof-node-01 (from remote, not guessed)
- No template residue in descriptors
- LOCAL MATERIALIZATION COMPLETE

## Topic Preservation — PASS

- Before: `["proof-node", "external-acceptance"]`
- After: `["proof-node", "external-acceptance", "agent-federation-node"]`
- Existing topics preserved, Federation topic added via `gh --add-topic`

## Quickstart + Drift — PASS

- PR-only guidance: "create a PR to main — once merged"
- No template fallback after quickstart

## NADI Local — PASS

- `nadi_daemon.py --once`: read-only, no keys
- `nadi_send.py`: signed NadiMessage, canonical path, no root outbox
- Message ID: `46f4ad71...`, source: `ag_0e5dbcaec5f95d57`

## Workflow — PENDING

Workflow secrets not configured. Remaining live proofs require FEDERATION_PAT and NODE_PRIVATE_KEY.

## Acceptance Matrix

| AT-REC | Status |
|--------|--------|
| AT-REC-001 through AT-REC-017 | Code: PASS. Live relay: pending secrets. |
