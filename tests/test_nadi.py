"""Gate 3 behaviour tests — NADI path, send, daemon modes, safety.

All remote operations use fakes; no real GitHub mutations.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
            "outbox": f"{location}/nadi_outbox.json",
            "inbox": f"{location}/nadi_inbox.json",
            "reports": f"{location}/reports/",
            "directives": f"{location}/directives/",
        },
    }
    peer_path = peer_dir / "peer.json"
    peer_path.write_text(json.dumps(peer_data, indent=2) + "\n")
    return peer_path


def _make_scripts(repo_dir: Path, *names: str) -> Path:
    """Copy named scripts into *repo_dir*/scripts/."""
    scripts_dest = repo_dir / "scripts"
    scripts_dest.mkdir(parents=True, exist_ok=True)
    for name in names:
        src = _SCRIPTS / name
        if src.exists():
            (scripts_dest / name).write_text(src.read_text())
    return scripts_dest


def _file_tree_snapshot(root: Path) -> dict[str, str]:
    """Return ``{relpath: sha256_hex}`` for all files under *root*."""
    snap: dict[str, str] = {}
    for f in sorted(root.rglob("*")):
        if f.is_file() and ".git" not in f.parts:
            rel = str(f.relative_to(root))
            snap[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
    return snap


# ── Tests ──────────────────────────────────────────────────────────────────


class TestNadiSendViaNadiNode:
    """nadi_send must emit through NadiNode, producing real NadiMessages."""

    def test_send_produces_signed_message(self, tmp_path: Path) -> None:
        _make_peer_json(tmp_path)
        _make_scripts(tmp_path, "nadi_send.py", "federation_utils.py")

        result = subprocess.run(
            [sys.executable, str(tmp_path / "scripts" / "nadi_send.py"),
             "send", "--to", "proof-target", "--op", "proof-op",
             "--payload", '{"value": 1}', "--priority", "3",
             "--ttl-seconds", "60"],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        assert result.returncode == 0, (
            f"exit={result.returncode}\nstderr={result.stderr}"
        )
        outbox = json.loads(
            (tmp_path / "data" / "federation" / "nadi_outbox.json").read_text()
        )
        assert len(outbox) == 1
        msg = outbox[0]
        assert msg["operation"] == "proof-op"
        assert msg["target"] == "proof-target"
        assert msg["payload"] == {"value": 1}
        assert msg["priority"] == 3
        assert msg.get("signature"), "must be signed"
        assert msg.get("payload_hash"), "must have payload_hash"
        assert isinstance(msg["source"], str) and len(msg["source"]) > 0
        # No legacy fields
        for legacy in ("source_city_id", "target_city_id", "ttl_ms",
                       "envelope_id", "nadi_type", "nadi_op"):
            assert legacy not in msg, f"legacy field {legacy} must not appear"

    def test_send_from_outside_repo_dir(self, tmp_path: Path) -> None:
        _make_peer_json(tmp_path)
        _make_scripts(tmp_path, "nadi_send.py", "federation_utils.py")

        import tempfile
        with tempfile.TemporaryDirectory() as td:
            result = subprocess.run(
                [sys.executable, str(tmp_path / "scripts" / "nadi_send.py"),
                 "send", "--to", "ext-test", "--op", "ping"],
                capture_output=True, text=True, cwd=td,
            )
        assert result.returncode == 0, f"send failed: {result.stderr}"
        outbox_path = tmp_path / "data" / "federation" / "nadi_outbox.json"
        assert outbox_path.exists()
        assert not Path(td).joinpath("nadi_outbox.json").exists()

    def test_corrupt_peer_json_errors(self, tmp_path: Path) -> None:
        _make_scripts(tmp_path, "nadi_send.py", "federation_utils.py")
        peer_dir = tmp_path / "data" / "federation"
        peer_dir.mkdir(parents=True, exist_ok=True)
        (peer_dir / "peer.json").write_text("{not json!!!")

        result = subprocess.run(
            [sys.executable, str(tmp_path / "scripts" / "nadi_send.py"),
             "send", "--to", "test", "--op", "test"],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        assert result.returncode != 0

    def test_payload_non_dict_rejected(self, tmp_path: Path) -> None:
        """List/string/number payloads must be rejected, no message written."""
        _make_peer_json(tmp_path)
        _make_scripts(tmp_path, "nadi_send.py", "federation_utils.py")

        result = subprocess.run(
            [sys.executable, str(tmp_path / "scripts" / "nadi_send.py"),
             "send", "--to", "test", "--op", "test",
             "--payload", '["not", "an", "object"]'],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        assert result.returncode != 0, (
            f"non-dict payload must be rejected, got {result.returncode}"
        )
        # No message should have been written
        outbox_path = tmp_path / "data" / "federation" / "nadi_outbox.json"
        if outbox_path.exists():
            outbox = json.loads(outbox_path.read_text())
            assert len(outbox) == 0, "no message should be written"


class TestNadiPathValidation:
    """Declarative nadi paths must match the actual transport contract."""

    def _call_validate(self, repo_dir: Path):
        from nadi_daemon import _validate_nadi_paths
        peer_path = repo_dir / "data" / "federation" / "peer.json"
        return _validate_nadi_paths(peer_path)

    def test_correct_paths_pass(self, tmp_path: Path) -> None:
        _make_peer_json(tmp_path)
        fed_dir, errors = self._call_validate(tmp_path)
        assert fed_dir is not None, f"expected success, got errors: {errors}"
        assert len(errors) == 0

    def test_wrong_outbox_fails(self, tmp_path: Path) -> None:
        _make_peer_json(tmp_path)
        # Overwrite with wrong declarative path
        peer_path = tmp_path / "data" / "federation" / "peer.json"
        peer = json.loads(peer_path.read_text())
        peer["nadi"]["outbox"] = "wrong/path/outbox.json"
        peer_path.write_text(json.dumps(peer, indent=2))
        fed_dir, errors = self._call_validate(tmp_path)
        assert fed_dir is None, "must fail on wrong outbox"
        assert any("outbox" in e.lower() for e in errors)

    def test_wrong_inbox_fails(self, tmp_path: Path) -> None:
        _make_peer_json(tmp_path)
        peer_path = tmp_path / "data" / "federation" / "peer.json"
        peer = json.loads(peer_path.read_text())
        peer["nadi"]["inbox"] = "wrong/path/inbox.json"
        peer_path.write_text(json.dumps(peer, indent=2))
        fed_dir, errors = self._call_validate(tmp_path)
        assert fed_dir is None
        assert any("inbox" in e.lower() for e in errors)

    def test_validation_creates_no_files(self, tmp_path: Path) -> None:
        _make_peer_json(tmp_path)
        snap_before = _file_tree_snapshot(tmp_path)
        self._call_validate(tmp_path)
        snap_after = _file_tree_snapshot(tmp_path)
        assert snap_before == snap_after, (
            "path validation must not create or modify any files"
        )


class TestDaemonReadOnlyLocal:
    """--once must be strictly read-only: no keys, no files, no mutations."""

    def test_once_creates_no_files(self, tmp_path: Path) -> None:
        _make_peer_json(tmp_path)
        _make_scripts(tmp_path, "nadi_daemon.py", "federation_utils.py")

        # Ensure .node_keys.json does not exist
        keys_path = tmp_path / "data" / "federation" / ".node_keys.json"
        assert not keys_path.exists(), "keys must not exist before --once"

        snap_before = _file_tree_snapshot(tmp_path)

        result = subprocess.run(
            [sys.executable, str(tmp_path / "scripts" / "nadi_daemon.py"),
             "--once"],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        assert result.returncode == 0, f"daemon failed: {result.stderr}"
        assert "Node:" in result.stdout

        snap_after = _file_tree_snapshot(tmp_path)
        assert snap_before == snap_after, (
            f"--once must not create/modify files.\n"
            f"before keys: {sorted(snap_before)}\n"
            f"after keys:  {sorted(snap_after)}\n"
            f"added: {set(snap_after) - set(snap_before)}"
        )
        assert not keys_path.exists(), (
            ".node_keys.json must not be created by --once"
        )

    def test_once_no_gh_subprocess(self, tmp_path: Path) -> None:
        _make_peer_json(tmp_path)
        _make_scripts(tmp_path, "nadi_daemon.py", "federation_utils.py")
        result = subprocess.run(
            [sys.executable, str(tmp_path / "scripts" / "nadi_daemon.py"),
             "--once"],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "gh api" not in result.stdout.lower()
        assert "github.com" not in result.stdout.lower()


class TestDaemonFakeRelay:
    """Relay modes with a fully controlled fake node — no real network."""

    @staticmethod
    def _fake_node():
        """Return a fake node-like object with call counters."""
        node = MagicMock()
        node.agent_id = "fake-agent"
        node.heartbeat = MagicMock(return_value=[])
        node.sync = MagicMock(return_value={
            "pulled": 0, "processed": 0, "pushed": 0, "expired": 0,
        })
        return node

    def test_relay_banner_appears(self) -> None:
        from nadi_daemon import _execute_mode
        args = argparse.Namespace(
            once=True, relay=True, interval=900, health=1.0, head_agent=None,
        )
        fake = self._fake_node()

        # Capture stdout
        import io
        saved_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            _execute_mode(args, node_loader=lambda: (fake, 0))
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = saved_stdout

        assert "REMOTE RELAY ENABLED" in output, (
            f"relay banner missing: {output}"
        )

    def test_relay_once_calls_heartbeat_and_sync(self) -> None:
        from nadi_daemon import _execute_mode
        args = argparse.Namespace(
            once=True, relay=True, interval=900, health=1.0, head_agent=None,
        )
        fake = self._fake_node()
        _execute_mode(args, node_loader=lambda: (fake, 0))

        assert fake.heartbeat.call_count == 1, (
            f"heartbeat: expected 1, got {fake.heartbeat.call_count}"
        )
        assert fake.sync.call_count == 1, (
            f"sync: expected 1, got {fake.sync.call_count}"
        )

    def test_local_once_does_not_call_heartbeat_or_sync(self) -> None:
        """--once without --relay never calls node_loader at all."""
        from nadi_daemon import _execute_mode

        node_loader_called = [0]

        def _counting_loader():
            node_loader_called[0] += 1
            fake = MagicMock()
            fake.heartbeat = MagicMock()
            fake.sync = MagicMock()
            return fake, 0

        args = argparse.Namespace(
            once=True, relay=False, interval=900, health=1.0, head_agent=None,
        )
        _execute_mode(args, node_loader=_counting_loader)
        assert node_loader_called[0] == 0, (
            "--once must not call node_loader (no NadiNode construction)"
        )


import argparse  # noqa: E402 — used above in TestDaemonFakeRelay


class TestMissingNadiKit:
    """When nadi-kit is genuinely absent, tools give clear UX, not traceback."""

    def test_nadi_send_guard_absent(self) -> None:
        from nadi_send import _load_nadi_node
        with patch("importlib.util.find_spec", return_value=None):
            node, exit_code = _load_nadi_node()
            assert node is None
            assert exit_code == 1

    def test_nadi_daemon_guard_absent(self) -> None:
        from nadi_daemon import _load_nadi_node
        with patch("importlib.util.find_spec", return_value=None):
            node, exit_code = _load_nadi_node()
            assert node is None
            assert exit_code == 1

    def test_broken_module_not_masked_as_absent(self, monkeypatch) -> None:
        """A findable but broken nadi-kit → visible failure, not skip."""
        monkeypatch.setattr(importlib.util, "find_spec",
                            lambda name, package=None: object())

        import builtins
        import sys as _sys
        _real_import = builtins.__import__
        _sys.modules.pop("nadi_kit", None)

        def _failing_import(name, *args, **kwargs):
            if name == "nadi_kit":
                raise ImportError("broken transitive deps")
            return _real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _failing_import)

        from nadi_daemon import _load_nadi_node
        node, exit_code = _load_nadi_node()
        assert node is None, "broken module → node=None"
        assert exit_code == 1, (
            f"broken module → visible controlled failure, exit=1, "
            f"got exit={exit_code}"
        )


class TestSetupPeerPreservation:
    """setup_node must preserve existing NADI data."""

    def _run_setup(self, repo_dir: Path, **kwargs):
        _make_scripts(repo_dir,
                      "setup_node.py", "federation_utils.py",
                      "render_federation_descriptor.py", "render_agent_card.py",
                      "export_authority_feed.py", "discover_federation_peers.py")
        gov_src = _SCRIPTS / "governance"
        gov_dest = repo_dir / "scripts" / "governance"
        if gov_src.exists():
            gov_dest.mkdir(exist_ok=True)
            for gov_file in gov_src.iterdir():
                if gov_file.is_file() and gov_file.suffix == ".py":
                    (gov_dest / gov_file.name).write_text(gov_file.read_text())
        (repo_dir / "docs" / "authority").mkdir(parents=True, exist_ok=True)
        caps_src = _SCRIPTS.parent / "docs" / "authority" / "capabilities.json"
        if caps_src.exists():
            (repo_dir / "docs" / "authority" / "capabilities.json").write_text(
                caps_src.read_text())
        seeds_dest = repo_dir / "data" / "federation" / "authority-descriptor-seeds.json"
        seeds_dest.parent.mkdir(parents=True, exist_ok=True)
        seeds_src = _SCRIPTS.parent / "data" / "federation" / "authority-descriptor-seeds.json"
        if seeds_src.exists():
            seeds_dest.write_text(seeds_src.read_text())
        else:
            seeds_dest.write_text(json.dumps({"descriptor_urls": []}))

        args = [sys.executable, str(repo_dir / "scripts" / "setup_node.py"),
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
        _make_peer_json(tmp_path)
        outbox_path = tmp_path / "data" / "federation" / "nadi_outbox.json"
        outbox_path.write_text(
            json.dumps([{"id": "existing-msg", "operation": "keep-me"}])
        )
        result = self._run_setup(
            tmp_path, name="Test Node", role="relay",
            repo="test-org/test-node",
        )
        assert result.returncode == 0, f"setup failed: {result.stderr}"
        outbox = json.loads(outbox_path.read_text())
        assert len(outbox) >= 1
        assert outbox[0]["id"] == "existing-msg"

    def test_corrupt_outbox_not_overwritten(self, tmp_path: Path) -> None:
        _make_peer_json(tmp_path)
        outbox_path = tmp_path / "data" / "federation" / "nadi_outbox.json"
        corrupt = "!!! not json !!!"
        outbox_path.write_text(corrupt)
        result = self._run_setup(
            tmp_path, name="Test Node", role="relay",
            repo="test-org/test-node",
        )
        assert result.returncode == 0
        assert outbox_path.read_text() == corrupt

    def test_peer_public_key_preserved(self, tmp_path: Path) -> None:
        peer_path = _make_peer_json(tmp_path)
        peer_data = json.loads(peer_path.read_text())
        peer_data["identity"]["public_key"] = "my-custom-ed25519-key"
        peer_path.write_text(json.dumps(peer_data, indent=2))
        result = self._run_setup(
            tmp_path, name="Test Node", role="governance",
            repo="test-org/test-node",
        )
        assert result.returncode == 0
        updated = json.loads(peer_path.read_text())
        assert updated["identity"]["public_key"] == "my-custom-ed25519-key"
        assert "governance-participation" in updated["capabilities"]
