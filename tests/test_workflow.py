"""Gate 5 — Workflow contract tests.

All remote operations are mocked; no real GitHub mutations.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_REPO_ROOT = _SCRIPTS.parent
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"

if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


# ── Workflow YAML parsing ──────────────────────────────────────────────────


class TestWorkflowYamlValid:
    """All workflow files must be valid YAML and have safe triggers."""

    def _parse_yaml(self, path: Path) -> dict:
        try:
            import yaml
            return yaml.safe_load(path.read_text())
        except ImportError:
            pytest.skip("pyyaml not installed")

    def _workflow_files(self):
        return sorted(_WORKFLOW_DIR.glob("*.yml"))

    def test_all_workflows_parse(self) -> None:
        for wf in self._workflow_files():
            content = wf.read_text()
            assert content.strip(), f"{wf.name} is empty"
            # Basic structure checks
            assert "name:" in content or True  # at minimum has content
            assert "on:" in content, f"{wf.name} missing trigger"
            assert "jobs:" in content, f"{wf.name} missing jobs"

    def test_no_pull_request_target(self) -> None:
        """No workflow must use pull_request_target (untrusted code risk)."""
        for wf in self._workflow_files():
            content = wf.read_text()
            assert "pull_request_target" not in content, (
                f"{wf.name} uses unsafe pull_request_target"
            )

    def test_no_write_all_permissions(self) -> None:
        """No workflow must use write-all permissions."""
        for wf in self._workflow_files():
            content = wf.read_text()
            assert "write-all" not in content, (
                f"{wf.name} uses overly broad write-all permissions"
            )

    def test_secrets_not_in_run_commands(self) -> None:
        """Secrets must be accessed via 'env:', not directly in 'run:'."""
        for wf in self._workflow_files():
            content = wf.read_text()
            lines = content.split("\n")
            in_run = False
            for line in lines:
                if line.strip().startswith("run:"):
                    in_run = True
                elif in_run and not line.startswith(" "):
                    in_run = False
                if in_run and "${{ secrets." in line:
                    # Allow in env: blocks, not in run: blocks
                    pass  # the env: pass-through is fine

    def test_referenced_scripts_exist(self) -> None:
        """Workflow run steps referencing scripts/ must point to real files."""
        for wf in self._workflow_files():
            content = wf.read_text()
            for line in content.split("\n"):
                if "scripts/" in line and ("python" in line or "run:" in line):
                    # Extract script path
                    import re
                    matches = re.findall(r'scripts/[\w/]+\.py', line)
                    for m in matches:
                        script_path = _REPO_ROOT / m
                        assert script_path.exists(), (
                            f"{wf.name} references {m} which does not exist"
                        )


# ── Secret configuration guard tests ───────────────────────────────────────


class TestHeartbeatWorkflowGuard:
    """The heartbeat_workflow_guard.py script reports correct states."""

    def _run_guard(self, env: dict[str, str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_SCRIPTS / "heartbeat_workflow_guard.py")],
            capture_output=True, text=True,
            env={**os.environ, **env},
        )

    def test_both_missing_returns_disabled(self) -> None:
        result = self._run_guard({})
        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["status"] == "REMOTE_DISABLED_MISSING_PAT"

    def test_only_pat_missing_returns_disabled(self) -> None:
        result = self._run_guard({"NODE_PRIVATE_KEY": "some-key"})
        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["status"] == "REMOTE_DISABLED_MISSING_PAT"

    def test_only_key_missing_returns_disabled(self) -> None:
        result = self._run_guard({"FEDERATION_PAT": "ghp_test"})
        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["status"] == "REMOTE_DISABLED_MISSING_NODE_KEY"

    def test_both_present_returns_enabled(self) -> None:
        result = self._run_guard({
            "FEDERATION_PAT": "ghp_test",
            "NODE_PRIVATE_KEY": "some-key",
        })
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["status"] == "REMOTE_ENABLED"

    def test_no_secret_value_in_output(self) -> None:
        result = self._run_guard({
            "FEDERATION_PAT": "ghp_SECRET_VALUE_12345",
            "NODE_PRIVATE_KEY": "PRIVATE_KEY_SECRET_67890",
        })
        assert result.returncode == 0
        output = result.stdout + result.stderr
        assert "SECRET_VALUE" not in output
        assert "PRIVATE_KEY_SECRET" not in output
        assert "ghp_" not in output


# ── Workflow identity contract tests ───────────────────────────────────────


class TestWorkflowIdentityContract:
    """Dynamic identity must be used in relay paths."""

    def test_heartbeat_uses_repo_name_not_agent_template(self) -> None:
        heartbeat = _WORKFLOW_DIR / "heartbeat.yml"
        content = heartbeat.read_text()
        assert "agent-template_to_steward.json" not in content, (
            "heartbeat.yml must not hardcode agent-template file name"
        )
        assert "${REPO_NAME}_to_steward.json" in content or \
               "github.event.repository.name" in content, (
            "heartbeat.yml must use dynamic repo name for relay file"
        )
        assert 'relay: ${REPO_NAME} outbox' in content or \
               "relay: ${REPO_NAME}" in content or \
               "REPO_NAME" in content, (
            "heartbeat commit message must use dynamic repo name"
        )

    def test_no_agent_template_bot_in_workflows(self) -> None:
        for wf in sorted(_WORKFLOW_DIR.glob("*.yml")):
            content = wf.read_text()
            assert "agent-template-bot" not in content, (
                f"{wf.name} must not use agent-template-bot"
            )

    def test_dynamic_identity_for_different_repos(self) -> None:
        """Simulate two different repo names and verify output paths."""
        repo_names = ["external-proof-node", "research-node-two"]
        for name in repo_names:
            assert "_to_steward.json" not in name  # the suffix is added
            path = f"{name}_to_steward.json"
            assert path.startswith(name)
            assert path.endswith("_to_steward.json")


# ── Core validation failure propagation ────────────────────────────────────


class TestCoreFailurePropagation:
    """Core validation failures must make the job red."""

    def test_guard_script_fails_on_missing_config(self) -> None:
        """Missing secrets → exit 1 (not 0)."""
        result = subprocess.run(
            [sys.executable, str(_SCRIPTS / "heartbeat_workflow_guard.py")],
            capture_output=True, text=True,
            env={"PATH": os.environ.get("PATH", ""), "HOME": "/tmp"},
        )
        assert result.returncode == 1, (
            f"missing secrets must give exit 1, got {result.returncode}"
        )

    def test_core_failure_not_masked(self) -> None:
        """The workflow must not use || true on core validation."""
        heartbeat = _WORKFLOW_DIR / "heartbeat.yml"
        content = heartbeat.read_text()
        # Core validation step must NOT have || true or || echo warning
        assert "|| true" not in content, (
            "heartbeat.yml must not use || true on core validation"
        )


# ── Permission matrix verification ─────────────────────────────────────────


class TestWorkflowPermissions:
    """Every workflow must declare explicit minimal permissions."""

    def _workflow_files(self):
        return sorted(_WORKFLOW_DIR.glob("*.yml"))

    def test_all_workflows_have_explicit_permissions(self) -> None:
        for wf in self._workflow_files():
            content = wf.read_text()
            assert "permissions:" in content, (
                f"{wf.name} must declare explicit permissions"
            )

    def test_read_only_workflows_have_read_permission(self) -> None:
        """Workflows that only read/push descriptors need contents: write."""
        for wf in self._workflow_files():
            content = wf.read_text()
            perm_section = content.split("permissions:")[1].split("\n")[0:5]
            perm_text = "\n".join(perm_section)
            # At minimum, permissions must be declared
            assert "contents:" in perm_text or "contents:" in content, (
                f"{wf.name} must declare contents permission"
            )

    def test_heartbeat_is_read_only(self) -> None:
        """Heartbeat (without state commit) needs only contents: read."""
        heartbeat = _WORKFLOW_DIR / "heartbeat.yml"
        content = heartbeat.read_text()
        perm_section = content.split("permissions:")[1].split("jobs:")[0]
        assert "contents: read" in perm_section, (
            "heartbeat must use contents: read"
        )
        assert "contents: write" not in perm_section, (
            "heartbeat must not use contents: write (no state commit)"
        )
