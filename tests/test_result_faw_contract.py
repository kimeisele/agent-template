"""The adapter result must match the canonical FAW RuntimeResult shape.

The runtime must know nothing about FAW (P3 hard constraint), so this test
checks the *field contract* structurally — the fields a FAW receipt
construction consumes (status, started_at, finished_at, artifacts, usage,
failure, evidence) must exist with the right types, without importing FAW.
"""

from datetime import datetime

from agent_runtime.result import RuntimeResult


def test_result_has_faw_contract_fields():
    r = RuntimeResult(status="succeeded")
    for name in ("status", "started_at", "finished_at", "artifacts", "usage", "failure", "evidence"):
        assert hasattr(r, name), f"missing FAW contract field: {name}"
    assert isinstance(r.started_at, datetime)
    assert isinstance(r.finished_at, datetime)
    assert isinstance(r.artifacts, tuple)
    assert isinstance(r.usage, dict)
    assert r.failure is None or isinstance(r.failure, dict)
    assert isinstance(r.evidence, tuple)


def test_result_keeps_adapter_debug_fields():
    r = RuntimeResult(status="failed", exit_code=1, wall_seconds=2.5, output_bytes=10,
                      event_count=3, stdout_path=None, stderr_path=None)
    assert r.exit_code == 1
    assert r.wall_seconds == 2.5
    assert r.output_bytes == 10
    assert r.event_count == 3


def test_no_faw_imports_in_result_module():
    import inspect
    from pathlib import Path
    import agent_runtime.result as mod
    src = Path(inspect.getfile(mod)).read_text(encoding="utf-8")
    assert "federated_agent_web" not in src
    assert "import nadi_kit" not in src
