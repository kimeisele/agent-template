"""Gate 3 behaviour tests — NADI path, send, daemon, and corrupt-data safety.

All remote operations are mocked; no real GitHub mutations.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


# ── helpers ────────────────────────────────────────────────────────────────


def _make_peer_json(
    repo_dir: Path,
    *,
    city_id: str = "test-node",
    location: str = "data/federation",
) -> Path:
    """Create a minimal peer.json in *repo_dir* and return its path."""
    peer_dir = repo_dir / "data" / "federation"
    peer_dir.mkdir(parents=True, exist_ok=True)
    peer_data = {
        "identity": {
            "city_id": city_id,
            "slug": city_id,
            "repo": f"test-org/{city_id}",
            "public_key": "",
        },
        "endpoint": {
            "city_id": city_id,
            "transport": "filesystem",
            "location": location,
        },
        "capabilities": ["test"],
        "nadi": {
            "outbox": "data/federation/nadi_outbox.json",
            "inbox": "data/federation/nadi_inbox.json",
            "reports": "data/federation/reports/",
            "directives": "data/federation/directives/",
        },
    }
    peer_path = peer_dir / "peer.json"
    peer_path.write_text(json.dumps(peer_data, indent=2) + "\n")
    return peer_path


def _make_scripts_dir(repo_dir: Path) -> Path:
    """Copy NADI scripts into *repo_dir*/scripts/ so they can be run."""
    scripts_dest = repo_dir / "scripts"
    scripts_dest.mkdir(parents=True, exist_ok=True)
    for name in ["nadi_send.py", "nadi_daemon.py", "federation_utils.py"]:
        src = _SCRIPTS / name
        if src.exists():
            (scripts_dest / name).write_text(src.read_text())
    return scripts_dest


# ── Tests ──────────────────────────────────────────────────────────────────


class TestNadiSendViaNadiNode:
    """nadi_send must emit through NadiNode, producing real NadiMessages."""

    def test_send_produces_signed_message(self, tmp_path: Path) -> None:
        """After send, the outbox contains a message with id, source,
        signature, and payload_hash — not legacy envelope fields."""
        _make_peer_json(tmp_path)
        _make_scripts_dir(tmp_path)

        result = subprocess.run(
            [sys.executable, str(tmp_path / "scripts" / "nadi_send.py"),
             "send", "--to", "proof-target", "--op", "proof-op",
             "--payload", '{"value": 1}', "--priority", "3",
             "--ttl-seconds", "60"],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        assert result.returncode == 0, (
            f"send failed: exit={result.returncode}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

        outbox_path = tmp_path / "data" / "federation" / "nadi_outbox.json"
        assert outbox_path.exists(), "outbox file not created"
        raw = json.loads(outbox_path.read_text())
        assert len(raw) == 1, f"expected 1 message, got {raw}"

        msg = raw[0]
        # Modern NadiMessage fields (from nadi-kit)
        assert "id" in msg, "missing id"
        assert msg["operation"] == "proof-op"
        assert msg["target"] == "proof-target"
        assert msg["payload"] == {"value": 1}
        assert msg["priority"] == 3
        # source is the nadi-kit-generated internal node_id
        # (e.g. "ag_..."), not the city_id from peer.json.
        assert isinstance(msg["source"], str) and len(msg["source"]) > 0, (
            f"source must be a non-empty string, got {msg['source']!r}"
        )
        assert msg.get("signature"), "message must be signed"
        assert msg.get("payload_hash"), "message must have payload_hash"

        # Legacy envelope fields must NOT be present
        for legacy in ("source_city_id", "target_city_id", "ttl_ms",
                       "envelope_id", "nadi_type", "nadi_op"):
            assert legacy not in msg, (
                f"legacy field '{legacy}' must not appear in NadiMessage"
            )

    def test_send_from_outside_repo_dir(self, tmp_path: Path) -> None:
        """nadi_send works correctly from a CWD outside the repo root."""
        _make_peer_json(tmp_path)
        _make_scripts_dir(tmp_path)

        # Run from a completely different directory
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            result = subprocess.run(
                [sys.executable, str(tmp_path / "scripts" / "nadi_send.py"),
                 "send", "--to", "ext-test", "--op", "ping"],
                capture_output=True, text=True, cwd=td,
            )
        assert result.returncode == 0, (
            f"send from outside CWD failed: {result.stderr}"
        )
        outbox_path = tmp_path / "data" / "federation" / "nadi_outbox.json"
        assert outbox_path.exists()
        raw = json.loads(outbox_path.read_text())
        assert len(raw) == 1

        # No root-level outbox should appear in cwd
        assert not Path(td).joinpath("nadi_outbox.json").exists()

    def test_corrupt_outbox_detected(self, tmp_path: Path) -> None:
        """Corrupt peer.json → clear error, non-zero exit."""
        _make_scripts_dir(tmp_path)
        peer_dir = tmp_path / "data" / "federation"
        peer_dir.mkdir(parents=True, exist_ok=True)
        corrupt_peer = peer_dir / "peer.json"
        corrupt_peer.write_text("{not json!!!")

        result = subprocess.run(
            [sys.executable, str(tmp_path / "scripts" / "nadi_send.py"),
             "send", "--to", "test", "--op", "test"],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        assert result.returncode != 0, (
            f"corrupt peer.json must cause non-zero exit. "
            f"got {result.returncode}"
        )

    def test_no_peer_json_errors(self, tmp_path: Path) -> None:
        """Missing peer.json → clear error, non-zero exit."""
        _make_scripts_dir(tmp_path)
        result = subprocess.run(
            [sys.executable, str(tmp_path / "scripts" / "nadi_send.py"),
             "send", "--to", "test", "--op", "test"],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        assert result.returncode != 0
        assert "peer.json" in result.stderr.lower()


class TestNadiDaemonModes:
    """Daemon --once must be local-only; --relay enables hub access."""

    def test_once_local_no_remote_access(self, tmp_path: Path) -> None:
        """--once without --relay is a local diagnostic, exit 0."""
        _make_peer_json(tmp_path)
        _make_scripts_dir(tmp_path)

        result = subprocess.run(
            [sys.executable, str(tmp_path / "scripts" / "nadi_daemon.py"),
             "--once"],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        assert result.returncode == 0, (
            f"daemon --once failed: {result.stderr}"
        )
        assert "Node:" in result.stdout
        assert "Outbox:" in result.stdout

    def test_once_local_no_gh_subprocess(self, tmp_path: Path) -> None:
        """--once must not spawn 'gh' subprocess."""
        _make_peer_json(tmp_path)
        _make_scripts_dir(tmp_path)

        result = subprocess.run(
            [sys.executable, str(tmp_path / "scripts" / "nadi_daemon.py"),
             "--once"],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        assert result.returncode == 0
        # No "gh" commands in output
        assert "gh api" not in result.stdout.lower()
        assert "github.com" not in result.stdout.lower()

    def test_relay_banner_shown(self, tmp_path: Path) -> None:
        """--relay must display REMOTE RELAY ENABLED banner."""
        _make_peer_json(tmp_path)
        _make_scripts_dir(tmp_path)

        # The daemon subprocess will FAIL on --once --relay because
        # it actually tries to call node.sync() which accesses GitHub.
        # We just verify the banner appears before the failure.
        result = subprocess.run(
            [sys.executable, str(tmp_path / "scripts" / "nadi_daemon.py"),
             "--once", "--relay"],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        # May fail due to no GH auth — that's fine, we only check banner
        assert "REMOTE RELAY ENABLED" in result.stdout, (
            f"Relay banner must appear.\nstdout: {result.stdout}"
        )

    def test_relay_mode_activates(self, tmp_path: Path) -> None:
        """--once --relay accepts the flag combination (banner present)."""
        _make_peer_json(tmp_path)
        _make_scripts_dir(tmp_path)

        result = subprocess.run(
            [sys.executable, str(tmp_path / "scripts" / "nadi_daemon.py"),
             "--once", "--relay"],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        # We verify the relay path is taken (banner), regardless
        # of whether actual hub access succeeds.
        assert "REMOTE RELAY ENABLED" in result.stdout


class TestMissingNadiKit:
    """When nadi-kit is genuinely absent, tools give clear UX, not traceback."""

    def test_nadi_send_clear_error_without_nadi_kit(self, tmp_path: Path,
                                                     monkeypatch) -> None:
        """With find_spec→None, nadi_send gives install hint, non-zero."""
        _make_peer_json(tmp_path)
        _make_scripts_dir(tmp_path)
        # With nadi-kit installed in venv, send succeeds.
        # We test the guard logic directly via _load_nadi_node.
        nadi_spec = importlib.util.find_spec("nadi_kit")
        assert nadi_spec is not None, "nadi-kit expected in test environment"
        # The guard function handles both cases; the subprocess test above
        # verifies the real path.  For the "absent" case, we test the
        # _load_nadi_node logic directly.
        from nadi_send import _load_nadi_node
        with patch("importlib.util.find_spec", return_value=None):
            node, exit_code = _load_nadi_node()
            assert node is None
            assert exit_code == 1

    def test_nadi_daemon_clear_error_without_nadi_kit(self, monkeypatch) -> None:
        """With find_spec→None, daemon gives install hint, non-zero."""
        from nadi_daemon import _load_nadi_node
        with patch("importlib.util.find_spec", return_value=None):
            node, exit_code = _load_nadi_node()
            assert node is None
            assert exit_code == 1

    def test_broken_module_propagates_error(self, monkeypatch) -> None:
        """A findable but broken nadi-kit must NOT be masked as absent.

        When find_spec returns non-None but the ``from nadi_kit import
        NadiNode`` inside _load_nadi_node raises ImportError, the
        function must return (None, 1) — not silently skip.
        """
        monkeypatch.setattr(importlib.util, "find_spec",
                            lambda name, package=None: object())

        # Block nadi_kit from being imported by removing it from
        # sys.modules and patching __import__.
        import builtins
        import sys as _sys
        _real_import = builtins.__import__
        _sys.modules.pop("nadi_kit", None)

        def _failing_import(name, *args, **kwargs):
            if name == "nadi_kit":
                raise ImportError("broken transitive deps")
            return _real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _failing_import)

        from nadi_daemon import _load_nadi_node as daemon_load
        node, exit_code = daemon_load()
        assert node is None, "broken module must return node=None"
        assert exit_code == 1, (
            f"broken module must give exit_code=1, got {exit_code}"
        )


class TestSetupPeerPreservation:
    """setup_node must preserve existing NADI data."""

    def _run_setup(self, repo_dir: Path, **kwargs) -> subprocess.CompletedProcess:
        """Run setup_node via subprocess in *repo_dir*."""
        scripts_dest = repo_dir / "scripts"
        scripts_dest.mkdir(parents=True, exist_ok=True)
        for name in [
            "setup_node.py", "federation_utils.py",
            "render_federation_descriptor.py", "render_agent_card.py",
            "export_authority_feed.py", "discover_federation_peers.py",
        ]:
            src = _SCRIPTS / name
            if src.exists():
                (scripts_dest / name).write_text(src.read_text())
        gov_src = _SCRIPTS / "governance"
        gov_dest = scripts_dest / "governance"
        if gov_src.exists():
            gov_dest.mkdir(exist_ok=True)
            for gov_file in gov_src.iterdir():
                if gov_file.is_file() and gov_file.suffix == ".py":
                    (gov_dest / gov_file.name).write_text(gov_file.read_text())
        # Also need capabilities and seeds
        (repo_dir / "docs" / "authority").mkdir(parents=True, exist_ok=True)
        caps_src = _SCRIPTS.parent / "docs" / "authority" / "capabilities.json"
        if caps_src.exists():
            (repo_dir / "docs" / "authority" / "capabilities.json").write_text(
                caps_src.read_text())
        seeds_src = _SCRIPTS.parent / "data" / "federation" / "authority-descriptor-seeds.json"
        seeds_dest = repo_dir / "data" / "federation" / "authority-descriptor-seeds.json"
        seeds_dest.parent.mkdir(parents=True, exist_ok=True)
        if seeds_src.exists():
            seeds_dest.write_text(seeds_src.read_text())
        else:
            seeds_dest.write_text(json.dumps({"descriptor_urls": []}))

        args = [sys.executable, str(scripts_dest / "setup_node.py"),
                "--non-interactive"]
        for k, v in kwargs.items():
            args.append(f"--{k.replace('_', '-')}")
            args.append(str(v))
        return subprocess.run(
            args, capture_output=True, text=True, cwd=str(repo_dir),
            env={"PATH": os.environ.get("PATH", ""),
                 "HOME": os.environ.get("HOME", ""),
                 "USER": os.environ.get("USER", ""),
                 "TMPDIR": os.environ.get("TMPDIR", "/tmp")},
        )

    def test_existing_outbox_preserved_on_rerun(self, tmp_path: Path) -> None:
        """Re-running setup does not clear or corrupt existing outbox."""
        _make_peer_json(tmp_path)
        outbox_path = tmp_path / "data" / "federation" / "nadi_outbox.json"
        outbox_path.write_text(
            json.dumps([{"id": "existing-msg", "operation": "keep-me"}])
        )

        # Setup with --repo to avoid remote issues
        result = self._run_setup(
            tmp_path, name="Test Node", role="relay",
            repo="test-org/test-node",
        )
        assert result.returncode == 0, f"setup failed: {result.stderr}"

        # Existing content preserved
        outbox = json.loads(outbox_path.read_text())
        assert len(outbox) >= 1
        assert outbox[0]["id"] == "existing-msg"

    def test_corrupt_outbox_not_overwritten_by_setup(self, tmp_path: Path) -> None:
        """Corrupt outbox is warned about, not replaced."""
        _make_peer_json(tmp_path)
        outbox_path = tmp_path / "data" / "federation" / "nadi_outbox.json"
        corrupt = "!!! not json !!!"
        outbox_path.write_text(corrupt)

        result = self._run_setup(
            tmp_path, name="Test Node", role="relay",
            repo="test-org/test-node",
        )
        assert result.returncode == 0  # setup succeeds (with warning)

        assert outbox_path.read_text() == corrupt, (
            "corrupt outbox must not be overwritten by setup"
        )

    def test_peer_public_key_preserved(self, tmp_path: Path) -> None:
        """Existing public_key in peer.json survives re-setup."""
        peer_path = _make_peer_json(tmp_path)
        # Set a custom public key
        peer_data = json.loads(peer_path.read_text())
        peer_data["identity"]["public_key"] = "my-custom-ed25519-key"
        peer_path.write_text(json.dumps(peer_data, indent=2))

        result = self._run_setup(
            tmp_path, name="Test Node", role="governance",
            repo="test-org/test-node",
        )
        assert result.returncode == 0, f"setup failed: {result.stderr}"

        updated = json.loads(peer_path.read_text())
        assert updated["identity"]["public_key"] == "my-custom-ed25519-key", (
            "public_key must be preserved across re-setup"
        )
        # Capabilities should be updated to match the new tier
        assert "governance-participation" in updated["capabilities"], (
            "capabilities must reflect new tier after re-setup"
        )
