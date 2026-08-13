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
        """Current candidate; kept behind the generic process boundary."""
        return cls(("openhands", "--headless", "--json"), environment=environment)

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

        combined_size = len(stdout) + len(stderr)
        oversized = combined_size > task.max_output_bytes
        stdout_path.write_bytes(stdout[: task.max_output_bytes])
        remaining = max(0, task.max_output_bytes - min(len(stdout), task.max_output_bytes))
        stderr_path.write_bytes(stderr[:remaining])
        events, parse_error = self._parse_jsonl(stdout)

        if timed_out:
            return RuntimeResult(
                "timed_out", process.returncode, elapsed, min(combined_size, task.max_output_bytes),
                len(events), stdout_path, stderr_path,
                failure={"code": "runtime.deadline", "message": "runtime exceeded wall-clock limit"},
            )
        if oversized:
            return RuntimeResult(
                "failed", process.returncode, elapsed, task.max_output_bytes,
                len(events), stdout_path, stderr_path,
                failure={"code": "runtime.output_limit", "message": "runtime output exceeded byte limit"},
            )
        if process.returncode != 0:
            return RuntimeResult(
                "failed", process.returncode, elapsed, combined_size, len(events), stdout_path, stderr_path,
                failure={"code": "runtime.exit", "message": f"runtime exited {process.returncode}"},
            )
        if parse_error is not None:
            return RuntimeResult(
                "failed", process.returncode, elapsed, combined_size, len(events), stdout_path, stderr_path,
                failure={"code": "runtime.invalid_jsonl", "message": parse_error},
            )
        return RuntimeResult(
            "succeeded", process.returncode, elapsed, combined_size, len(events), stdout_path, stderr_path,
            metadata={"terminal_event": events[-1] if events else None},
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
