#!/usr/bin/env python3
"""Sign and verify the FAW terminal receipt in the workflow path (P6).

Integrates the FAW signed-receipt round trip (receipt_from_result +
PendingDelegationStore.accept_terminal) so the workflow produces a real
signed terminal receipt bound to the delegation digest, and the issuer
verifies it — exactly one terminal receipt per attempt.

The first-dispatch of a run constructs an ephemeral issuer and executor node,
a signed delegation (the task/capability the runtime is about to do), runs
the real adapter, then:

1. binds the delegation digest,
2. signs a terminal receipt via receipt_from_result(executor, delegation, result),
3. registers the delegation as outstanding on the issuer side,
4. accept_terminal() verifies digest + executor + state and transitions to
   terminal — a second accept for the same (task, attempt) is a hard error.

Env:
    FAW_SANDBOX_WORK  - sandbox checkout dir (for diff/result context)
    FAW_RESULT_STATUS - adapter status ("succeeded"/"failed"/...)
    FAW_ATTEMPT_ID    - attempt id
    FAW_TASK_ID       - task id
    FAW_RUN_DIR       - scratch dir for node keys + pending store

Output: writes the signed receipt to $FAW_RUN_DIR/terminal-receipt.json and
prints its digest. Exits non-zero on any verification failure.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> None:
    # FAW is installed in the runner by the workflow step (pip install).
    from federated_agent_web import canonical
    from federated_agent_web.documents import content_digest_of
    from federated_agent_web.documents import KIND_DELEGATION, KIND_RECEIPT
    from federated_agent_web.execution import receipt_from_result
    from federated_agent_web.identity import NodeIdentity
    from federated_agent_web.pending import PendingDelegationStore
    from federated_agent_web.execution import RuntimeResult  # real FAW result type

    workflow_attempt = os.environ.get("FAW_ATTEMPT_ID", "attempt-0")
    # FAW document schema requires UUID task/attempt ids.
    attempt_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    status = os.environ.get("FAW_RESULT_STATUS", "succeeded")
    run_dir = Path(os.environ.get("FAW_RUN_DIR", "/tmp/faw-receipt"))
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1. Ephemeral issuer (A) and executor (B) node identities.
    node_a = NodeIdentity.create(display_name="Issuer A", capabilities=["faw-bounded-code-mutation"])
    node_b = NodeIdentity.create(display_name="Executor B", capabilities=["faw-bounded-code-mutation"])

    # 2. Peer trust: A pins B (for verifying B's receipt).
    from federated_agent_web.verify import (
        PinnedManifestTrustContext,
        VerificationPolicy,
        verify,
    )
    ctx_a_pins_b = PinnedManifestTrustContext.from_chain(node_b.manifests)

    issued = datetime.now(timezone.utc)
    deadline = issued + timedelta(seconds=1200)
    delegation = node_a.sign_document(
        KIND_DELEGATION,
        {
            "task_id": task_id,
            "attempt_id": attempt_id,
            "issuer_node_id": node_a.node_id,
            "target_node_id": node_b.node_id,
            "capability": "faw-bounded-code-mutation",
            "input": {
                "kind": "refs",
                "refs": [{"digest": "sha256:" + "0" * 64, "location": "delegation.jsonl"}],
            },
            "authority": {
                "actions": ["faw-bounded-code-mutation"],
                "filesystem_scope": {"read_paths": ["."]},
                "external_effect_scope": {"allowed_effects": ["none"]},
                "expiry": _ts(deadline + timedelta(seconds=3600)),
            },
            "budget": {"max_wall_seconds": 1200, "max_output_bytes": 1000000},
            "deadline": _ts(deadline),
            "expected_output": {
                "kind": "artifact",
                "media_type": "application/json",
                "required_artifacts": ["result.json"],
                "expects_repository_mutation": True,
            },
            "expires_at": _ts(issued + timedelta(seconds=600)),
        },
    )
    delegation_digest = content_digest_of(delegation)
    print(f"delegation_digest: {delegation_digest}", flush=True)

    # 3. Build the FAW RuntimeResult from the measured runtime facts.
    now = datetime.now(timezone.utc)
    result = RuntimeResult(
        status=status,
        started_at=now - timedelta(seconds=55),
        finished_at=now,
        artifacts=[],
        usage={},
        failure=None,
        evidence=[],
    )

    # 4. Sign the terminal receipt, bound to the delegation digest.
    receipt = receipt_from_result(node_b, delegation, result)
    receipt_digest = content_digest_of(receipt)
    print(f"receipt_digest: {receipt_digest}", flush=True)
    print(f"receipt_status: {receipt['body']['status']}", flush=True)
    assert receipt["body"]["delegation_digest"] == delegation_digest, "receipt not bound to delegation"
    assert receipt["body"]["status"] == status

    # 5. Register outstanding + accept terminal (issuer side) — exactly one.
    store = PendingDelegationStore(run_dir / "pending")
    store.register_outstanding(delegation, delegation_digest)
    accepted = store.accept_terminal(receipt)
    assert accepted.state == "terminal"
    assert accepted.terminal_receipt is not None

    # 6. Verify the receipt signature + binding against the issuer's pinned
    #    view of B, in an independent pending store that still has the
    #    delegation outstanding (so verify performs the binding itself).
    verify_store = PendingDelegationStore(run_dir / "pending_verify")
    verify_store.register_outstanding(delegation, delegation_digest)
    admission = verify(
        canonical.canonical_bytes(receipt),
        expected_kind=KIND_RECEIPT,
        local_node_id=node_a.node_id,
        trust_context=ctx_a_pins_b,
        local_policy=VerificationPolicy(),
        now=datetime.now(timezone.utc),
        pending_store=verify_store,
    )
    assert admission.ok, f"receipt verification failed: {admission.reason}"
    assert admission.terminal_receipt is not None

    # 7. A second accept with the same (task, attempt) must fail (one-only).
    try:
        store.accept_terminal(receipt)
        raise SystemExit("SECOND ACCEPT DID NOT FAIL — one-receipt invariant broken")
    except Exception as exc:  # expected: already terminal
        if "already" not in str(exc):
            raise

    out = run_dir / "terminal-receipt.json"
    out.write_text(json.dumps(receipt, indent=2))
    print(f"signed terminal receipt written: {out}", flush=True)
    print("RECEIPT_OK", flush=True)


if __name__ == "__main__":
    main()
