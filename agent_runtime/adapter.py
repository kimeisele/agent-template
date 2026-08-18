"""One-shot subprocess adapter for a headless JSONL coding runtime.

The runtime is an external executable and may use a different Python version.
Task content is written to a file and never interpolated into a shell command.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .result import RuntimeResult


@dataclass(frozen=True)
class RuntimeTask:
    prompt: str
    max_wall_seconds: float
    max_output_bytes: int


class HeadlessRuntimeAdapter:
    """Invoke an argv-defined runtime with a task-file flag and JSONL output."""

    def __init__(
        self,
        executable: Sequence[str],
        *,
        task_file_flag: str = "-f",
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if not executable or any(not isinstance(part, str) or not part for part in executable):
            raise ValueError("executable must be a non-empty argv sequence")
        self.executable = tuple(executable)
        self.task_file_flag = task_file_flag
        self.environment = dict(environment or {})

    @classmethod
    def openhands(cls, *, environment: Mapping[str, str] | None = None) -> "HeadlessRuntimeAdapter":
        """Current candidate; kept behind the generic process boundary.

        Honors FAW_RUNTIME_EXECUTABLE (absolute path to the runtime binary,
        e.g. a Python 3.12 venv) so the node code (3.11) never needs the
        runtime's Python on PATH. Falls back to ``openhands`` on PATH.
        """
        executable = os.environ.get("FAW_RUNTIME_EXECUTABLE", "openhands")
        return cls((executable, "--headless", "--json"), environment=environment)

    def execute(self, task: RuntimeTask, workdir: Path) -> RuntimeResult:
        if task.max_wall_seconds <= 0:
            raise ValueError("max_wall_seconds must be positive")
        if task.max_output_bytes < 0:
            raise ValueError("max_output_bytes must be non-negative")

        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        task_path = workdir / "task.md"
        stdout_path = workdir / "runtime.stdout.jsonl"
        stderr_path = workdir / "runtime.stderr.log"
        task_path.write_text(task.prompt, encoding="utf-8")

        argv = [*self.executable, self.task_file_flag, str(task_path)]
        env = os.environ.copy()
        env.update(self.environment)
        started = time.monotonic()
        _started_dt = datetime.now(timezone.utc)
        process = subprocess.Popen(
            argv,
            cwd=workdir,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=task.max_wall_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
        elapsed = time.monotonic() - started
        _finished_dt = datetime.now(timezone.utc)

        combined_size = len(stdout) + len(stderr)
        oversized = combined_size > task.max_output_bytes
        stdout_path.write_bytes(stdout[: task.max_output_bytes])
        remaining = max(0, task.max_output_bytes - min(len(stdout), task.max_output_bytes))
        stderr_path.write_bytes(stderr[:remaining])
        events, parse_error = self._parse_jsonl(stdout)
        # openhands prints an ASCII banner and some diagnostics to stderr
        # before the JSONL event stream; when stdout is not JSONL but stderr
        # carries real bytes (a provider error or a relocated stream), parse
        # stderr instead. An empty stderr still fails closed (no events).
        if parse_error is not None and stderr.strip():
            events, parse_error = self._parse_jsonl(stderr)

        if timed_out:
            return RuntimeResult(
                status="timed_out",
                started_at=_started_dt,
                finished_at=_finished_dt,
                artifacts=(),
                usage={},
                failure={"code": "runtime.deadline", "message": "runtime exceeded wall-clock limit"},
                evidence=(),
                exit_code=process.returncode,
                wall_seconds=elapsed,
                output_bytes=min(combined_size, task.max_output_bytes),
                event_count=len(events),
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
        if oversized:
            return RuntimeResult(
                status="failed",
                started_at=_started_dt,
                finished_at=_finished_dt,
                failure={"code": "runtime.output_limit", "message": "runtime output exceeded byte limit"},
                exit_code=process.returncode,
                wall_seconds=elapsed,
                output_bytes=task.max_output_bytes,
                event_count=len(events),
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
        if process.returncode != 0:
            return RuntimeResult(
                status="failed",
                started_at=_started_dt,
                finished_at=_finished_dt,
                failure={"code": "runtime.exit", "message": f"runtime exited {process.returncode}"},
                exit_code=process.returncode,
                wall_seconds=elapsed,
                output_bytes=combined_size,
                event_count=len(events),
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
        if parse_error is not None:
            return RuntimeResult(
                status="failed",
                started_at=_started_dt,
                finished_at=_finished_dt,
                failure={"code": "runtime.invalid_jsonl", "message": parse_error},
                exit_code=process.returncode,
                wall_seconds=elapsed,
                output_bytes=combined_size,
                event_count=len(events),
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
        return RuntimeResult(
            status="succeeded",
            started_at=_started_dt,
            finished_at=_finished_dt,
            artifacts=(),
            usage={},
            evidence=({"event": events[-1]} if events else ()),
            exit_code=process.returncode,
            wall_seconds=elapsed,
            output_bytes=combined_size,
            event_count=len(events),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

    @staticmethod
    def _parse_jsonl(raw: bytes) -> tuple[list[dict], str | None]:
        events = []
        for index, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                return events, f"invalid JSONL at line {index}: {exc}"
            if not isinstance(event, dict):
                return events, f"JSONL line {index} is not an object"
            events.append(event)
        return events, None
