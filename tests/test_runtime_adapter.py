"""Offline process-boundary tests for the headless runtime adapter."""

import json
import sys
from pathlib import Path

from agent_runtime import HeadlessRuntimeAdapter, RuntimeTask


def _stub(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "stub_runtime.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_task_is_passed_by_file_without_shell_interpolation(tmp_path):
    stub = _stub(tmp_path, """
import json, pathlib, sys
task = pathlib.Path(sys.argv[sys.argv.index('-f') + 1]).read_text()
print(json.dumps({'task': task, 'argv': sys.argv[1:]}))
""")
    prompt = "$(touch SHOULD_NOT_EXIST); `echo nope`; hello"
    adapter = HeadlessRuntimeAdapter((sys.executable, str(stub)))
    result = adapter.execute(RuntimeTask(prompt, 5, 4096), tmp_path / "work")
    assert result.status == "succeeded"
    event = json.loads(result.stdout_path.read_text())
    assert event["task"] == prompt
    assert not (tmp_path / "work" / "SHOULD_NOT_EXIST").exists()


def test_nonzero_exit_is_normalized(tmp_path):
    stub = _stub(tmp_path, "import sys; print('{}'); sys.exit(7)\n")
    result = HeadlessRuntimeAdapter((sys.executable, str(stub))).execute(
        RuntimeTask("task", 5, 4096), tmp_path / "work"
    )
    assert result.status == "failed"
    assert result.exit_code == 7
    assert result.failure["code"] == "runtime.exit"


def test_deadline_terminates_process_group(tmp_path):
    stub = _stub(tmp_path, "import time; time.sleep(30)\n")
    result = HeadlessRuntimeAdapter((sys.executable, str(stub))).execute(
        RuntimeTask("task", 0.1, 4096), tmp_path / "work"
    )
    assert result.status == "timed_out"
    assert result.wall_seconds < 6


def test_output_limit_fails_closed_and_bounds_artifacts(tmp_path):
    stub = _stub(tmp_path, "print('x' * 10000)\n")
    result = HeadlessRuntimeAdapter((sys.executable, str(stub))).execute(
        RuntimeTask("task", 5, 128), tmp_path / "work"
    )
    assert result.status == "failed"
    assert result.failure["code"] == "runtime.output_limit"
    assert result.stdout_path.stat().st_size + result.stderr_path.stat().st_size <= 128


def test_invalid_jsonl_fails_closed(tmp_path):
    stub = _stub(tmp_path, "print('not-json')\n")
    result = HeadlessRuntimeAdapter((sys.executable, str(stub))).execute(
        RuntimeTask("task", 5, 4096), tmp_path / "work"
    )
    assert result.status == "failed"
    assert result.failure["code"] == "runtime.invalid_jsonl"
