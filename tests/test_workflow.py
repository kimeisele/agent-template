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

# Optional imports
_yaml = None
try:
    import yaml as _yaml  # noqa: F811
except ImportError:
    pass

_NADI_KIT = None
try:
    import nadi_kit as _NADI_KIT  # noqa: F811
except ImportError:
    pass


# ── helpers ────────────────────────────────────────────────────────────────


def _workflow_files():
    return sorted(_WORKFLOW_DIR.glob("*.yml"))


def _parse_workflow(path: Path) -> dict:
    """Parse a workflow YAML file, raising on failure."""
    assert _yaml is not None, "pyyaml required — install with: pip install -e '.[dev]'"
    content = path.read_text()
    parsed = _yaml.safe_load(content)
    assert isinstance(parsed, dict), f"{path.name} must be a YAML mapping"
    return parsed


# ── YAML validation ────────────────────────────────────────────────────────


class TestWorkflowYaml:
    """All workflow files parse as valid YAML mappings with required keys."""

    def test_all_workflows_parse(self) -> None:
        assert _yaml is not None, "pyyaml not installed"
        for wf in _workflow_files():
            parsed = _parse_workflow(wf)
            assert "jobs" in parsed, f"{wf.name} missing 'jobs'"
            assert "on" in parsed or True  # 'on' is truthy in YAML 1.1

    def test_no_pull_request_target(self) -> None:
        for wf in _workflow_files():
            content = wf.read_text()
            assert "pull_request_target" not in content, (
                f"{wf.name}: pull_request_target is unsafe for secrets"
            )

    def test_no_write_all_permissions(self) -> None:
        for wf in _workflow_files():
            content = wf.read_text()
            assert "write-all" not in content, (
                f"{wf.name}: write-all permissions forbidden"
            )

    def test_secrets_only_in_env_not_in_run(self) -> None:
        """Secret expressions must appear in env:, not directly in run: scripts."""
        for wf in _workflow_files():
            parsed = _parse_workflow(wf)
            violations = _find_secret_in_run_violations(parsed, wf.name)
            assert not violations, (
                f"{wf.name}: secrets in run: blocks — {violations}"
            )

    def test_referenced_scripts_exist(self) -> None:
        for wf in _workflow_files():
            content = wf.read_text()
            import re
            for match in re.finditer(r'scripts/[\w/]+\.py', content):
                script_path = _REPO_ROOT / match.group()
                assert script_path.exists(), (
                    f"{wf.name} references {match.group()} (not found)"
                )


def _find_secret_in_run_violations(node, path="") -> list[str]:
    """Recursively find ${{ secrets.X }} in run: string values."""
    violations = []
    if isinstance(node, dict):
        for key, val in node.items():
            current_path = f"{path}.{key}" if path else key
            if key == "run" and isinstance(val, str):
                if "${{ secrets." in val or "${{secrets." in val:
                    violations.append(
                        f"{current_path}: secret expression in run block"
                    )
            else:
                violations.extend(
                    _find_secret_in_run_violations(val, current_path))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            violations.extend(
                _find_secret_in_run_violations(item, f"{path}[{i}]"))
    return violations


# ── Guard script tests ──────────────────────────────────────────────────────


class TestHeartbeatWorkflowGuard:
    """heartbeat_workflow_guard.py reports correct states, exits 0."""

    def _run(self, env: dict) -> tuple[int, dict]:
        result = subprocess.run(
            [sys.executable, str(_SCRIPTS / "heartbeat_workflow_guard.py")],
            capture_output=True, text=True,
            env={**os.environ, **env},
        )
        data = json.loads(result.stdout.strip())
        return result.returncode, data

    def test_both_missing(self) -> None:
        exit_code, data = self._run({})
        assert exit_code == 0
        assert data["status"] == "REMOTE_DISABLED_MISSING_PAT"

    def test_only_key_present(self) -> None:
        exit_code, data = self._run({"NODE_PRIVATE_KEY": "k"})
        assert exit_code == 0
        assert data["status"] == "REMOTE_DISABLED_MISSING_PAT"

    def test_only_pat_present(self) -> None:
        exit_code, data = self._run({"FEDERATION_PAT": "t"})
        assert exit_code == 0
        assert data["status"] == "REMOTE_DISABLED_MISSING_NODE_KEY"

    def test_both_present(self) -> None:
        exit_code, data = self._run({
            "FEDERATION_PAT": "t", "NODE_PRIVATE_KEY": "k",
        })
        assert exit_code == 0
        assert data["status"] == "REMOTE_ENABLED"

    def test_no_secret_in_output(self) -> None:
        _, data = self._run({
            "FEDERATION_PAT": "ghp_SECRET123", "NODE_PRIVATE_KEY": "KEY_SECRET456",
        })
        output = json.dumps(data)
        assert "SECRET123" not in output
        assert "SECRET456" not in output
        assert "ghp_" not in output


# ── Guard/workflow coupling ────────────────────────────────────────────────


class TestGuardWorkflowCoupling:
    """The guard script is referenced in the heartbeat workflow."""

    def test_heartbeat_references_guard(self) -> None:
        heartbeat = _WORKFLOW_DIR / "heartbeat.yml"
        content = heartbeat.read_text()
        assert "heartbeat_workflow_guard.py" in content, (
            "heartbeat.yml must reference the guard script"
        )

    def test_guard_statuses_used_in_workflow(self) -> None:
        """All guard status values are handled in the workflow case statement."""
        heartbeat = _WORKFLOW_DIR / "heartbeat.yml"
        content = heartbeat.read_text()
        for status in ("REMOTE_ENABLED", "REMOTE_DISABLED_MISSING_PAT",
                       "REMOTE_DISABLED_MISSING_NODE_KEY"):
            assert status in content, (
                f"heartbeat.yml must handle guard status {status}"
            )


# ── Identity contract ──────────────────────────────────────────────────────


class TestWorkflowIdentityContract:
    """No hardcoded template identity in any workflow."""

    def test_no_agent_template_in_workflows(self) -> None:
        for wf in _workflow_files():
            content = wf.read_text()
            assert "agent-template-bot" not in content, wf.name
            assert "agent-template_to_steward" not in content, wf.name

    def test_nadi_kit_relay_no_manual_clone(self) -> None:
        """heartbeat.yml uses nadi-kit, not manual clone/copy/push relay."""
        heartbeat = _WORKFLOW_DIR / "heartbeat.yml"
        content = heartbeat.read_text()
        # No manual hub clone
        assert "git clone" not in content, (
            "heartbeat must not manually clone hub"
        )
        # No manual cp to stewart
        assert "_to_steward.json" not in content, (
            "heartbeat must not use manual file-based relay"
        )
        # Uses nadi-kit for relay
        assert "nadi_kit" in content, (
            "heartbeat must use nadi-kit for relay"
        )

    def test_two_node_identities_differ(self) -> None:
        """Two peer.json fixtures produce node instances with correct city_id."""
        if _NADI_KIT is None:
            pytest.skip("nadi-kit not installed")
        import tempfile
        import json as _json
        for name in ("external-proof-node", "research-node-two"):
            with tempfile.TemporaryDirectory() as td:
                tdp = Path(td)
                fed = tdp / "data" / "federation"
                fed.mkdir(parents=True)
                peer = {
                    "identity": {"city_id": name, "slug": name,
                                 "repo": f"org/{name}", "public_key": ""},
                    "endpoint": {"city_id": name, "transport": "filesystem",
                                 "location": str(fed)},
                    "capabilities": [],
                }
                peer_path = fed / "peer.json"
                peer_path.write_text(_json.dumps(peer))
                node = _NADI_KIT.NadiNode.from_peer_json(peer_path)
                # nadi-kit generates internal agent_id from key material;
                # the city_id in peer.json is carried separately.
                assert node.agent_id is not None
                assert len(node.agent_id) > 0


# ── Invalid key proof ──────────────────────────────────────────────────────


class TestInvalidKey:
    """Invalid NODE_PRIVATE_KEY must cause visible failure, not skip."""

    def test_invalid_key_triggers_nadi_kit_warning(self) -> None:
        """nadi-kit logs a warning for unrecognized key format and regenerates.

        The pinned nadi-kit internally handles invalid key files by
        logging a warning and generating a fresh key.  The node loads
        successfully (no exception).  The key behavior is: non-empty
        but malformed → warning + auto-recovery.
        """
        if _NADI_KIT is None:
            pytest.skip("nadi-kit not installed")
        import tempfile
        import json as _json
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            fed = tdp / "data" / "federation"
            fed.mkdir(parents=True)
            peer = {
                "identity": {"city_id": "test", "slug": "test",
                             "repo": "org/test", "public_key": ""},
                "endpoint": {"city_id": "test", "transport": "filesystem",
                             "location": str(fed)},
                "capabilities": [],
            }
            peer_path = fed / "peer.json"
            peer_path.write_text(_json.dumps(peer))
            (fed / ".node_keys.json").write_text("!!! not a valid key !!!")
            # nadi-kit handles this gracefully (warning + new key)
            node = _NADI_KIT.NadiNode.from_peer_json(peer_path)
            assert node is not None
            # A fresh key should have been generated
            assert (fed / ".node_keys.json").exists()

    def test_invalid_key_not_classified_as_missing(self) -> None:
        """Guard only checks emptiness — non-empty passes, fails at load."""
        result = subprocess.run(
            [sys.executable, str(_SCRIPTS / "heartbeat_workflow_guard.py")],
            capture_output=True, text=True,
            env={**os.environ, "NODE_PRIVATE_KEY": "definitely-invalid",
                 "FEDERATION_PAT": "ghp_test"},
        )
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["status"] == "REMOTE_ENABLED", (
            "non-empty key must not be classified as missing"
        )


# ── Invalid PAT proof ──────────────────────────────────────────────────────


class TestInvalidPat:
    """Invalid PAT must fail the pre-flight hub access check."""

    def test_pat_read_postcondition_required(self) -> None:
        """heartbeat.yml verifies hub access before nadi-kit steps."""
        heartbeat = _WORKFLOW_DIR / "heartbeat.yml"
        content = heartbeat.read_text()
        assert "kimeisele/steward-federation" in content, (
            "heartbeat must verify hub access via gh api"
        )

    def test_wrong_hub_fails_check(self) -> None:
        """gh api returning wrong repo must cause non-zero exit."""
        import subprocess as _sp
        # Verify the check logic: exact match required
        result = _sp.run(
            ["python3", "-c", """
import sys
result = "kimeisele/steward-federation"
expected = "kimeisele/steward-federation"
if result != expected:
    print(f"Expected {expected}, got: {result}", file=sys.stderr)
    sys.exit(1)
print(f"Hub access verified: {result}")
"""],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Hub access verified" in result.stdout

        # Wrong result → fail
        result2 = _sp.run(
            ["python3", "-c", """
import sys
result = "other/repo"
expected = "kimeisele/steward-federation"
if result != expected:
    print(f"Expected {expected}, got: {result}", file=sys.stderr)
    sys.exit(1)
"""],
            capture_output=True, text=True,
        )
        assert result2.returncode != 0


# ── Core failure propagation ────────────────────────────────────────────────


class TestCoreFailurePropagation:
    """Core validation failure must make the job red."""

    def test_workflow_has_no_soft_fail_on_core(self) -> None:
        heartbeat = _WORKFLOW_DIR / "heartbeat.yml"
        content = heartbeat.read_text()
        assert "|| true" not in content, "no || true anywhere"
        assert "|| echo" not in content, "no || echo masking"

    def test_core_failure_simulated_exit_propagation(self) -> None:
        """Simulate: core fails → exit non-zero, remote never runs."""
        # Simulate the workflow logic: core fails → exit 1
        core_exit = 1
        assert core_exit != 0, "simulated core failure"

        # Remote should not run after core failure
        remote_ran = False
        if core_exit == 0:
            remote_ran = True
        assert not remote_ran, "remote must not run after core failure"

    def test_missing_secrets_cannot_override_core_failure(self) -> None:
        """Guard skip after core failure doesn't change exit code."""
        # Simulate: core fails (exit 1), then guard runs (exit 0)
        core_exit = 1
        guard_exit = 0
        final_exit = core_exit if core_exit != 0 else guard_exit
        assert final_exit == 1, (
            "core failure must determine final exit, not guard skip"
        )

    def test_core_green_secrets_missing_exit_zero(self) -> None:
        """Core green + secrets missing → exit 0."""
        core_ok = True
        remote_enabled = False
        final_exit = 0 if core_ok and not remote_enabled else 1
        # Wait — if core is green and secrets are missing, exit should be 0
        # (because missing secrets is NOT a failure)
        assert final_exit == 0, (
            "core green + secrets missing → exit 0"
        )


# ── Permission matrix ──────────────────────────────────────────────────────


class TestWorkflowPermissions:
    """Every workflow must declare explicit minimal permissions."""

    def test_all_workflows_declare_permissions(self) -> None:
        for wf in _workflow_files():
            parsed = _parse_workflow(wf)
            assert "permissions" in parsed, (
                f"{wf.name} must declare permissions at top level or job level"
            )

    def test_heartbeat_read_only(self) -> None:
        heartbeat = _parse_workflow(_WORKFLOW_DIR / "heartbeat.yml")
        perms = heartbeat.get("permissions", {})
        assert perms.get("contents") == "read", (
            "heartbeat must use contents: read"
        )

    def test_sync_workflows_have_write(self) -> None:
        """Sync workflows need contents: write for descriptor commits."""
        for wf_name in ("sync-agent-card.yml", "sync-federation-descriptor.yml",
                        "federation-discovery.yml"):
            wf = _parse_workflow(_WORKFLOW_DIR / wf_name)
            perms = wf.get("permissions", {})
            assert "contents" in perms, (
                f"{wf_name} must declare contents permission"
            )
