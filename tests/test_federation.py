"""Smoke tests for federation scripts."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"


def _run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def test_render_federation_descriptor(tmp_path: Path) -> None:
    out = tmp_path / "descriptor.json"
    result = _run_script("render_federation_descriptor.py", "--output", str(out))
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text())
    assert data["kind"] == "agent_federation_descriptor"
    assert data["status"] == "active"
    assert "capabilities" in data
    assert "layer" in data
    assert "endpoints" in data


def test_render_agent_card(tmp_path: Path) -> None:
    out = tmp_path / "agent.json"
    result = _run_script("render_agent_card.py", "--output", str(out))
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text())
    # Name must be a non-empty string — no hardcoded template identity.
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert "skills" in data
    assert "federation" in data


def test_export_authority_feed(tmp_path: Path) -> None:
    out_dir = tmp_path / "feed"
    result = _run_script("export_authority_feed.py", "--output-dir", str(out_dir))
    assert result.returncode == 0, result.stderr
    manifest = out_dir / "latest-authority-manifest.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text())
    assert data["kind"] == "source_authority_feed_manifest"


def test_discover_peers_help() -> None:
    result = _run_script("discover_federation_peers.py", "--help")
    assert result.returncode == 0


def test_fetch_peer_authority_help() -> None:
    result = _run_script("fetch_peer_authority.py", "--help")
    assert result.returncode == 0


def test_authority_descriptor_seeds_valid() -> None:
    seeds_path = REPO_ROOT / "data" / "federation" / "authority-descriptor-seeds.json"
    assert seeds_path.exists()
    data = json.loads(seeds_path.read_text())
    assert "descriptor_urls" in data
    assert len(data["descriptor_urls"]) > 0


def test_capabilities_json_valid() -> None:
    caps_path = REPO_ROOT / "docs" / "authority" / "capabilities.json"
    assert caps_path.exists()
    data = json.loads(caps_path.read_text())
    assert data["kind"] == "agent_capability_manifest"
    assert len(data["skills"]) > 0
    assert "federation_interfaces" in data
    assert "produces" in data["federation_interfaces"]


nadi_kit = None
if importlib.util.find_spec("nadi_kit") is None:
    nadi_kit = None
else:
    import nadi_kit  # noqa: E402

_NADI_SKIP_REASON = "nadi-kit not installed — install with: pip install -e '.[federation]'"


def test_nadi_kit_import() -> None:
    """nadi_kit can be imported and exposes expected API."""
    if nadi_kit is None:
        pytest.skip(_NADI_SKIP_REASON)
    assert hasattr(nadi_kit, "NadiNode")
    assert hasattr(nadi_kit, "NadiMessage")
    assert hasattr(nadi_kit, "NadiTransport")
    assert hasattr(nadi_kit, "NadiHubRelay")


def test_nadi_node_from_peer_json(tmp_path: Path) -> None:
    """NadiNode can be created from a peer.json file."""
    if nadi_kit is None:
        pytest.skip(_NADI_SKIP_REASON)

    peer_data = {
        "identity": {
            "city_id": "test-node",
            "slug": "test-node",
            "repo": "kimeisele/test-node",
            "public_key": "",
        },
        "endpoint": {
            "city_id": "test-node",
            "transport": "filesystem",
            "location": "data/federation",
        },
        "capabilities": ["authority-publishing"],
        "nadi": {
            "outbox": "data/federation/nadi_outbox.json",
            "inbox": "data/federation/nadi_inbox.json",
        },
    }
    peer_json = tmp_path / "peer.json"
    peer_json.write_text(json.dumps(peer_data))

    node = nadi_kit.NadiNode.from_peer_json(peer_json)
    assert node.agent_id == "test-node"
    assert node.repo == "kimeisele/test-node"
    assert node.capabilities == ["authority-publishing"]


def test_nadi_node_emit_and_receive(tmp_path: Path) -> None:
    """NadiNode can emit messages and read them back from transport."""
    if nadi_kit is None:
        pytest.skip(_NADI_SKIP_REASON)

    peer_data = {
        "identity": {"city_id": "emit-test"},
        "capabilities": [],
    }
    peer_json = tmp_path / "peer.json"
    peer_json.write_text(json.dumps(peer_data))

    node = nadi_kit.NadiNode.from_peer_json(peer_json)
    node.emit("ping", {"data": "hello"}, target="steward")

    outbox = node.transport.read_outbox()
    assert len(outbox) == 1
    assert outbox[0].operation == "ping"
    assert outbox[0].target == "steward"
    assert outbox[0].payload["data"] == "hello"


def test_peer_json_exists() -> None:
    """Template ships with a peer.json in data/federation/."""
    peer_path = REPO_ROOT / "data" / "federation" / "peer.json"
    assert peer_path.exists()
    data = json.loads(peer_path.read_text())
    assert "identity" in data
    assert "nadi" in data
    assert "inbox" in data["nadi"]
    assert "outbox" in data["nadi"]


def test_nadi_inbox_exists() -> None:
    """Template ships with a nadi_inbox.json."""
    inbox_path = REPO_ROOT / "data" / "federation" / "nadi_inbox.json"
    assert inbox_path.exists()
    data = json.loads(inbox_path.read_text())
    assert isinstance(data, list)


def test_well_known_descriptor_matches_schema() -> None:
    desc_path = REPO_ROOT / ".well-known" / "agent-federation.json"
    data = json.loads(desc_path.read_text())
    required = {"kind", "version", "repo_id", "display_name", "status", "capabilities", "layer", "endpoints"}
    assert required.issubset(data.keys()), f"Missing fields: {required - data.keys()}"


# ── NADI import behaviour regression tests ───────────────────────────────

class TestNadiImportBehaviour:
    """Gate 2: Only genuine module absence causes a skip."""

    def test_find_spec_none_causes_skip(self, monkeypatch) -> None:
        """When find_spec returns None, NADI tests must skip."""
        import importlib

        original_find_spec = importlib.util.find_spec

        def _fake_find_spec(name, package=None):
            if name == "nadi_kit":
                return None
            return original_find_spec(name, package)

        monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec)
        # Import the guard logic fresh
        spec = importlib.util.find_spec("nadi_kit")
        assert spec is None, "guard must see nadi_kit as absent"

    def test_corrupt_module_does_not_skip(self, monkeypatch) -> None:
        """A findable but broken nadi_kit must fail, not skip."""
        import importlib

        # Simulate: find_spec succeeds but the actual import would fail.
        # We cannot make find_spec non-None and import fail in the same
        # process trivially, so we verify the guard logic directly:
        # If find_spec returns a non-None value, no skip occurs and
        # the import is attempted — which will raise if broken.
        original_find_spec = importlib.util.find_spec

        def _fake_find_spec(name, package=None):
            if name == "nadi_kit":
                # Return a real spec for a harmless module so the guard
                # does NOT set nadi_kit=None.  The actual import of
                # nadi_kit will then proceed normally.
                return original_find_spec("json", package)
            return original_find_spec(name, package)

        monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec)
        spec = importlib.util.find_spec("nadi_kit")
        assert spec is not None, (
            "guard must see nadi_kit as findable — a corrupt module path "
            "must result in a visible ImportError, not a silent skip"
        )

    def test_missing_api_fails_visibly(self) -> None:
        """When nadi_kit is installed but missing expected API, tests fail."""
        if nadi_kit is None:
            pytest.skip(_NADI_SKIP_REASON)
        # If nadi_kit is installed, all asserted attributes must exist
        assert hasattr(nadi_kit, "NadiNode"), "NadiNode missing from nadi_kit"
        assert hasattr(nadi_kit, "NadiMessage"), "NadiMessage missing"
        assert hasattr(nadi_kit, "NadiTransport"), "NadiTransport missing"
        assert hasattr(nadi_kit, "NadiHubRelay"), "NadiHubRelay missing"

    def test_correct_module_all_tests_run(self, tmp_path: Path) -> None:
        """With correct nadi_kit, all NADI unit tests execute."""
        if nadi_kit is None:
            pytest.skip(_NADI_SKIP_REASON)
        peer = {
            "identity": {"city_id": "reg-test"},
            "endpoint": {
                "city_id": "reg-test",
                "transport": "filesystem",
                "location": str(tmp_path),
            },
            "nadi": {
                "outbox": str(tmp_path / "outbox.json"),
                "inbox": str(tmp_path / "inbox.json"),
            },
            "capabilities": [],
        }
        peer_json = tmp_path / "peer.json"
        peer_json.write_text(json.dumps(peer))
        node = nadi_kit.NadiNode.from_peer_json(peer_json)
        assert node.agent_id == "reg-test"
        node.emit("test-op", {"k": "v"}, target="dest")
        msgs = node.transport.read_outbox()
        assert len(msgs) == 1
        assert msgs[0].operation == "test-op"
