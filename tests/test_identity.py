"""Tests for Gate 1 — Identity resolution, renderer drift, README block.

All tests are local; no remote GitHub mutations.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure scripts/ is importable
_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from federation_utils import (  # noqa: E402
    _parse_github_full_name,
    _TEMPLATE_REPO,
    repo_from_git_remote,
    repo_from_setup_config,
    resolve_repo_identity,
)


# ── 1. Git remote parsing ───────────────────────────────────────────────────


class TestGitRemoteParsing:
    def test_parse_https(self) -> None:
        assert _parse_github_full_name(
            "https://github.com/kimeisele/my-node.git"
        ) == "kimeisele/my-node"

    def test_parse_https_no_git_suffix(self) -> None:
        assert _parse_github_full_name(
            "https://github.com/kimeisele/my-node"
        ) == "kimeisele/my-node"

    def test_parse_ssh_colon(self) -> None:
        assert _parse_github_full_name(
            "git@github.com:kimeisele/my-node.git"
        ) == "kimeisele/my-node"

    def test_parse_ssh_protocol(self) -> None:
        assert _parse_github_full_name(
            "ssh://git@github.com/kimeisele/my-node.git"
        ) == "kimeisele/my-node"

    def test_parse_non_github(self) -> None:
        assert _parse_github_full_name("https://gitlab.com/org/repo.git") is None

    def test_parse_trailing_slash(self) -> None:
        assert _parse_github_full_name(
            "https://github.com/owner/repo.git/"
        ) == "owner/repo"

    @patch("subprocess.run")
    def test_repo_from_git_remote_success(self, mock_run) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="https://github.com/kimeisele/my-node.git", stderr="",
        )
        result = repo_from_git_remote(Path("/fake"))
        assert result == "kimeisele/my-node"

    @patch("subprocess.run")
    def test_repo_from_git_remote_failure(self, mock_run) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error",
        )
        result = repo_from_git_remote(Path("/fake"))
        assert result is None


# ── 2. Config file reading ──────────────────────────────────────────────────


class TestConfigReading:
    def test_repo_from_setup_config_valid(self, tmp_path: Path) -> None:
        config = tmp_path / ".federation-setup.json"
        config.write_text(json.dumps({"github_repo": "owner/my-node"}))
        result = repo_from_setup_config(tmp_path)
        assert result == "owner/my-node"

    def test_repo_from_setup_config_missing(self, tmp_path: Path) -> None:
        result = repo_from_setup_config(tmp_path)
        assert result is None

    def test_repo_from_setup_config_invalid_json(self, tmp_path: Path) -> None:
        config = tmp_path / ".federation-setup.json"
        config.write_text("not json")
        result = repo_from_setup_config(tmp_path)
        assert result is None

    def test_repo_from_setup_config_no_repo_field(self, tmp_path: Path) -> None:
        config = tmp_path / ".federation-setup.json"
        config.write_text(json.dumps({"display_name": "X"}))
        result = repo_from_setup_config(tmp_path)
        assert result is None


# ── 3. Identity resolution ──────────────────────────────────────────────────


class TestIdentityResolution:
    """Test the canonical resolution order from D1."""

    @patch("subprocess.run")
    @patch.dict("os.environ", {}, clear=True)
    def test_explicit_repo_wins(self, mock_run) -> None:
        """Explicit --repo is used regardless of remote."""
        result = resolve_repo_identity(
            Path("/fake"), explicit_repo="test-org/test-node",
        )
        assert result == "test-org/test-node"

    @patch("subprocess.run")
    @patch.dict("os.environ", {}, clear=True)
    def test_git_remote_used_without_explicit(self, mock_run, tmp_path) -> None:
        """Git remote is authoritative when no explicit --repo."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="https://github.com/real-org/real-repo.git", stderr="",
        )
        # Also write a stray config with a different value
        config = tmp_path / ".federation-setup.json"
        config.write_text(json.dumps({"github_repo": "other-org/other-repo"}))

        result = resolve_repo_identity(tmp_path)
        # Remote wins over config
        assert result == "real-org/real-repo"

    @patch("subprocess.run")
    @patch.dict("os.environ", {}, clear=True)
    def test_config_used_when_no_remote(self, mock_run, tmp_path) -> None:
        """When git remote fails, saved config is used."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error",
        )
        config = tmp_path / ".federation-setup.json"
        config.write_text(json.dumps({"github_repo": "config-org/config-repo"}))

        result = resolve_repo_identity(tmp_path)
        assert result == "config-org/config-repo"

    @patch("subprocess.run")
    @patch.dict("os.environ", {"GITHUB_REPOSITORY": "env-org/env-repo"}, clear=True)
    def test_env_used_when_no_remote_and_no_config(self, mock_run) -> None:
        """GITHUB_REPOSITORY is the last fallback before failure."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error",
        )
        result = resolve_repo_identity(Path("/fake"))
        assert result == "env-org/env-repo"

    def test_fails_when_nothing_available(self, tmp_path: Path) -> None:
        """Fail closed when no source provides identity."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=1, stdout="", stderr="error",
                )
                with pytest.raises(RuntimeError, match="Cannot determine repository identity"):
                    resolve_repo_identity(tmp_path)

    def test_explicit_repo_validation(self) -> None:
        """Invalid --repo format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid repository format"):
            resolve_repo_identity(Path("/fake"), explicit_repo="no-slash")

    def test_template_identity_not_hardcoded_default(self, tmp_path: Path) -> None:
        """The constant TEMPLATE_REPO exists but is never a default."""
        assert _TEMPLATE_REPO == "kimeisele/agent-template"
        # With no sources, we fail — not fall back to template
        with patch.dict("os.environ", {}, clear=True):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=1, stdout="", stderr="error",
                )
                with pytest.raises(RuntimeError):
                    resolve_repo_identity(tmp_path)


# ── 4. Renderer drift prevention ────────────────────────────────────────────


class TestRendererDrift:
    """Renderer output must not change identity after setup."""

    def test_descriptor_uses_resolved_identity(self, tmp_path: Path) -> None:
        """Renderer produces output matching the explicit --repo."""
        out = tmp_path / "descriptor.json"
        result = subprocess.run(
            [sys.executable, str(_SCRIPTS / "render_federation_descriptor.py"),
             "--output", str(out), "--repo", "proof-org/proof-node"],
            capture_output=True, text=True, cwd=str(_SCRIPTS.parent),
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(out.read_text())
        assert data["repo_id"] == "proof-node"
        assert data["authority_feed_manifest_url"].startswith(
            "https://raw.githubusercontent.com/proof-org/proof-node/"
        )

    def test_agent_card_uses_resolved_identity(self, tmp_path: Path) -> None:
        """Agent card output matches the explicit --repo."""
        out = tmp_path / "agent.json"
        result = subprocess.run(
            [sys.executable, str(_SCRIPTS / "render_agent_card.py"),
             "--output", str(out), "--repo", "proof-org/proof-node"],
            capture_output=True, text=True, cwd=str(_SCRIPTS.parent),
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(out.read_text())
        assert data["url"] == "https://github.com/proof-org/proof-node"

    def test_descriptor_no_template_fallback_in_output(self, tmp_path: Path) -> None:
        """With explicit --repo, template identity must NOT appear in output."""
        out = tmp_path / "descriptor.json"
        subprocess.run(
            [sys.executable, str(_SCRIPTS / "render_federation_descriptor.py"),
             "--output", str(out), "--repo", "independent/node"],
            capture_output=True, text=True, cwd=str(_SCRIPTS.parent),
        )
        raw = out.read_text()
        assert "kimeisele/agent-template" not in raw
        assert "agent-template" not in json.loads(raw)["repo_id"]

    def test_renderer_fails_without_identity(self, tmp_path: Path) -> None:
        """Renderer must fail (non-zero exit) with no identity source.

        The renderer computes ``repo_root = parents[1]`` relative to the
        script file.  By copying the scripts into *tmp_path* and running
        from there, the root becomes *tmp_path* — which has no git remote,
        no setup config, and (with a clean env) no ``GITHUB_REPOSITORY``.
        """
        scripts_dest = tmp_path / "scripts"
        scripts_dest.mkdir()
        for name in ["render_federation_descriptor.py", "federation_utils.py"]:
            src = _SCRIPTS / name
            if src.exists():
                (scripts_dest / name).write_text(src.read_text())

        caps_dest = tmp_path / "docs" / "authority"
        caps_dest.mkdir(parents=True, exist_ok=True)
        caps_src = _SCRIPTS.parent / "docs" / "authority" / "capabilities.json"
        if caps_src.exists():
            (caps_dest / "capabilities.json").write_text(caps_src.read_text())
        else:
            (caps_dest / "capabilities.json").write_text(json.dumps({"skills": []}))

        result = subprocess.run(
            [sys.executable, str(scripts_dest / "render_federation_descriptor.py"),
             "--output", str(tmp_path / "descriptor.json")],
            capture_output=True, text=True, cwd=str(tmp_path),
            env={"PATH": os.environ.get("PATH", ""),
                 "HOME": os.environ.get("HOME", ""),
                 "USER": os.environ.get("USER", ""),
                 "TMPDIR": os.environ.get("TMPDIR", "/tmp")},
        )
        assert result.returncode != 0, (
            f"Renderer must fail when identity cannot be resolved. "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )


# ── 5. Template residue checks ──────────────────────────────────────────────


class TestTemplateResidue:
    """No kimeisele/agent-template in materialized artifacts."""

    def test_descriptor_no_template_residue_with_override(self, tmp_path: Path) -> None:
        """With explicit identity, descriptors carry no template residue."""
        out = tmp_path / "descriptor.json"
        subprocess.run(
            [sys.executable, str(_SCRIPTS / "render_federation_descriptor.py"),
             "--output", str(out), "--repo", "custom-org/custom-node"],
            capture_output=True, text=True, cwd=str(_SCRIPTS.parent),
        )
        raw = out.read_text()
        assert "kimeisele/agent-template" not in raw

    def test_agent_card_no_template_residue_with_override(self, tmp_path: Path) -> None:
        """With explicit identity, agent card carries no template residue.

        Uses an isolated temp directory with its own ``.well-known/``
        so the template checkout does not leak identity.
        """
        # Set up isolated environment: scripts + well-known for descriptor.
        scripts_dest = tmp_path / "scripts"
        scripts_dest.mkdir()
        for name in ["render_federation_descriptor.py", "render_agent_card.py",
                      "federation_utils.py"]:
            src = _SCRIPTS / name
            if src.exists():
                (scripts_dest / name).write_text(src.read_text())

        well_known = tmp_path / ".well-known"
        well_known.mkdir()

        caps_dest = tmp_path / "docs" / "authority"
        caps_dest.mkdir(parents=True, exist_ok=True)
        caps_src = _SCRIPTS.parent / "docs" / "authority" / "capabilities.json"
        if caps_src.exists():
            (caps_dest / "capabilities.json").write_text(caps_src.read_text())
        else:
            (caps_dest / "capabilities.json").write_text(json.dumps({"skills": []}))

        desc_out = tmp_path / ".well-known" / "agent-federation.json"
        subprocess.run(
            [sys.executable, str(scripts_dest / "render_federation_descriptor.py"),
             "--output", str(desc_out), "--repo", "custom-org/custom-node"],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        agent_out = tmp_path / ".well-known" / "agent.json"
        subprocess.run(
            [sys.executable, str(scripts_dest / "render_agent_card.py"),
             "--output", str(agent_out), "--repo", "custom-org/custom-node"],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        raw = agent_out.read_text()
        assert "kimeisele/agent-template" not in raw
        assert "Agent Template" not in raw


# ── 6. Idempotency and structural test identity ─────────────────────────────


class TestStructuralIdentity:
    """Tests assert on structure, not hardcoded identity names."""

    def test_agent_card_name_is_non_empty_string(self, tmp_path: Path) -> None:
        """Agent card name field is present and non-empty for any identity."""
        out = tmp_path / "agent.json"
        subprocess.run(
            [sys.executable, str(_SCRIPTS / "render_agent_card.py"),
             "--output", str(out), "--repo", "my-org/my-node"],
            capture_output=True, text=True, cwd=str(_SCRIPTS.parent),
        )
        data = json.loads(out.read_text())
        assert isinstance(data["name"], str)
        assert len(data["name"]) > 0

    def test_render_accepts_non_template_identity(self, tmp_path: Path) -> None:
        """Renderer must succeed with any valid identity, not just the template."""
        # Generate descriptor first so agent card has a matching source.
        desc_out = tmp_path / "descriptor.json"
        subprocess.run(
            [sys.executable, str(_SCRIPTS / "render_federation_descriptor.py"),
             "--output", str(desc_out), "--repo", "external-user/external-proof-node"],
            capture_output=True, text=True, cwd=str(_SCRIPTS.parent),
        )
        out = tmp_path / "agent.json"
        result = subprocess.run(
            [sys.executable, str(_SCRIPTS / "render_agent_card.py"),
             "--output", str(out), "--repo", "external-user/external-proof-node"],
            capture_output=True, text=True, cwd=str(_SCRIPTS.parent),
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(out.read_text())
        # Name from descriptor's display_name ("External Proof Node") or repo_name
        assert isinstance(data["name"], str) and len(data["name"]) > 0
        assert "kimeisele" not in data["url"]
        assert "external-user/external-proof-node" in data["url"]


# ── 7. README identity block tests ──────────────────────────────────────────


class TestReadmeIdentityBlock:
    """The README identity block is idempotent and safe."""

    def _run_setup(self, repo_root: Path, name: str, role: str, repo: str) -> None:
        """Run non-interactive setup targeting *repo_root*.

        Copies scripts into *repo_root* so that ``REPO_ROOT`` (computed
        as ``parents[1]`` relative to the script file) resolves to
        *repo_root* rather than the original checkout.
        """
        scripts_dest = repo_root / "scripts"
        scripts_dest.mkdir(parents=True, exist_ok=True)
        for script_name in [
            "setup_node.py", "federation_utils.py",
            "render_federation_descriptor.py", "render_agent_card.py",
            "export_authority_feed.py", "discover_federation_peers.py",
        ]:
            src = _SCRIPTS / script_name
            if src.exists():
                dest = scripts_dest / script_name
                dest.write_text(src.read_text())

        gov_src = _SCRIPTS / "governance"
        gov_dest = scripts_dest / "governance"
        if gov_src.exists():
            gov_dest.mkdir(exist_ok=True)
            for gov_file in gov_src.iterdir():
                if gov_file.is_file() and gov_file.suffix == ".py":
                    (gov_dest / gov_file.name).write_text(gov_file.read_text())

        result = subprocess.run(
            [sys.executable, str(scripts_dest / "setup_node.py"),
             "--non-interactive", "--name", name, "--role", role,
             "--repo", repo, "--org", "dummy"],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        assert result.returncode == 0, f"setup failed: {result.stderr}"

    def test_block_inserted_once(self, tmp_path: Path) -> None:
        """First setup inserts the identity block."""
        self._setup_minimal_repo(tmp_path, "custom-org/custom-node")

        readme = tmp_path / "README.md"
        self._write_minimal_readme(readme)

        self._run_setup(tmp_path, "Test Node", "relay", "custom-org/custom-node")

        content = readme.read_text()
        assert "<!-- BEGIN FEDERATION NODE IDENTITY -->" in content
        assert "<!-- END FEDERATION NODE IDENTITY -->" in content
        assert "Test Node" in content
        assert "custom-org/custom-node" in content
        # Only one block
        assert content.count("<!-- BEGIN FEDERATION NODE IDENTITY -->") == 1
        assert content.count("<!-- END FEDERATION NODE IDENTITY -->") == 1

    def test_block_idempotent_on_rerun(self, tmp_path: Path) -> None:
        """Second setup does not duplicate the block."""
        self._setup_minimal_repo(tmp_path, "custom-org/custom-node")

        readme = tmp_path / "README.md"
        self._write_minimal_readme(readme)

        self._run_setup(tmp_path, "First Run", "relay", "custom-org/custom-node")

        self._run_setup(tmp_path, "Second Run", "research", "custom-org/custom-node")
        second_hash = readme.read_text()

        # Still exactly one block
        assert second_hash.count("<!-- BEGIN FEDERATION NODE IDENTITY -->") == 1
        assert second_hash.count("<!-- END FEDERATION NODE IDENTITY -->") == 1
        # Content updated for second run
        assert "Second Run" in second_hash
        assert "Research Faculty" in second_hash

    def test_user_content_outside_block_preserved(self, tmp_path: Path) -> None:
        """User text outside the identity block is untouched."""
        self._setup_minimal_repo(tmp_path, "custom-org/custom-node")

        readme = tmp_path / "README.md"
        user_text = "This is my custom documentation.\nIt spans multiple lines.\n"
        readme.write_text(
            "# My Node\n\n<!-- BEGIN FEDERATION NODE IDENTITY -->\n"
            "> **Node:** Old Identity\n"
            "<!-- END FEDERATION NODE IDENTITY -->\n\n" + user_text
        )

        self._run_setup(tmp_path, "New Node", "relay", "custom-org/custom-node")

        content = readme.read_text()
        assert user_text in content
        assert "New Node" in content
        assert "Old Identity" not in content
        assert content.count("<!-- BEGIN FEDERATION NODE IDENTITY -->") == 1

    def test_malformed_markers_rejected(self, tmp_path: Path) -> None:
        """Multiple BEGIN markers → warning, no corruption."""
        self._setup_minimal_repo(tmp_path, "custom-org/custom-node")

        readme = tmp_path / "README.md"
        original = (
            "# Broken\n\n<!-- BEGIN FEDERATION NODE IDENTITY -->\n"
            "stuff\n<!-- BEGIN FEDERATION NODE IDENTITY -->\n"
            "more\n<!-- END FEDERATION NODE IDENTITY -->\n"
        )
        readme.write_text(original)

        self._run_setup(tmp_path, "Node", "relay", "custom-org/custom-node")

        # File should be unchanged (malformed → skipped)
        assert readme.read_text() == original

    def _setup_minimal_repo(self, repo_dir: Path, _repo: str) -> None:
        """Create a minimal checkout skeleton for setup_node."""
        (repo_dir / "scripts").mkdir(parents=True, exist_ok=True)
        (repo_dir / "docs" / "authority").mkdir(parents=True, exist_ok=True)
        (repo_dir / "data" / "federation").mkdir(parents=True, exist_ok=True)
        (repo_dir / ".well-known").mkdir(parents=True, exist_ok=True)

        # Symlink/copy scripts so setup can import its dependencies
        scripts_dir = repo_dir / "scripts"
        for name in [
            "setup_node.py", "federation_utils.py",
            "render_federation_descriptor.py", "render_agent_card.py",
            "export_authority_feed.py", "discover_federation_peers.py",
        ]:
            src = _SCRIPTS / name
            dest = scripts_dir / name
            if src.exists() and not dest.exists():
                dest.write_text(src.read_text())

        # Copy governance subpackage
        gov_src = _SCRIPTS / "governance"
        gov_dest = scripts_dir / "governance"
        if gov_src.exists() and not gov_dest.exists():
            gov_dest.mkdir(exist_ok=True)
            for gov_file in gov_src.iterdir():
                if gov_file.is_file() and gov_file.suffix == ".py":
                    (gov_dest / gov_file.name).write_text(gov_file.read_text())

        # Copy capabilities for loading
        caps_src = _SCRIPTS.parent / "docs" / "authority" / "capabilities.json"
        caps_dest = repo_dir / "docs" / "authority" / "capabilities.json"
        if caps_src.exists():
            caps_dest.write_text(caps_src.read_text())
        else:
            caps_dest.write_text(json.dumps({"skills": []}))

        # Copy seeds for peer discovery
        seeds_src = _SCRIPTS.parent / "data" / "federation" / "authority-descriptor-seeds.json"
        seeds_dest = repo_dir / "data" / "federation" / "authority-descriptor-seeds.json"
        if seeds_src.exists():
            seeds_dest.write_text(seeds_src.read_text())

    @staticmethod
    def _write_minimal_readme(readme: Path) -> None:
        readme.write_text("# Test Node\n\nSome user documentation here.\n")


# ── 8. Non-interactive setup identity separation ────────────────────────────


class TestNonInteractiveSetupIdentity:
    """Repository slug and display name are separate, not guessed."""

    def _run_setup(self, repo_root: Path, **kwargs) -> subprocess.CompletedProcess:
        """Run non-interactive setup with scripts copied to *repo_root*."""
        scripts_dest = repo_root / "scripts"
        scripts_dest.mkdir(parents=True, exist_ok=True)
        for script_name in [
            "setup_node.py", "federation_utils.py",
            "render_federation_descriptor.py", "render_agent_card.py",
            "export_authority_feed.py", "discover_federation_peers.py",
        ]:
            src = _SCRIPTS / script_name
            if src.exists():
                (scripts_dest / script_name).write_text(src.read_text())

        gov_src = _SCRIPTS / "governance"
        gov_dest = scripts_dest / "governance"
        if gov_src.exists():
            gov_dest.mkdir(exist_ok=True)
            for gov_file in gov_src.iterdir():
                if gov_file.is_file() and gov_file.suffix == ".py":
                    (gov_dest / gov_file.name).write_text(gov_file.read_text())

        args = [sys.executable, str(scripts_dest / "setup_node.py"), "--non-interactive"]
        for k, v in kwargs.items():
            args.append(f"--{k.replace('_', '-')}")
            args.append(str(v))
        return subprocess.run(args, capture_output=True, text=True, cwd=str(repo_root))

    def test_config_saves_detected_repo_not_guessed(self, tmp_path: Path) -> None:
        """When remote is X/Y and --name is Z, github_repo must be X/Y, not guessed."""
        self._setup_minimal_repo(tmp_path, "real-org/real-slug")

        # Simulate a git remote
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text(
            '[remote "origin"]\n\turl = https://github.com/real-org/real-slug.git\n'
        )

        self._run_setup(tmp_path, name="Different Display Name", role="relay",
                       repo="real-org/real-slug")

        config_path = tmp_path / ".federation-setup.json"
        assert config_path.exists()
        config = json.loads(config_path.read_text())
        assert config["display_name"] == "Different Display Name"
        # github_repo must be the real remote, NOT a guess from display name
        assert config["github_repo"] == "real-org/real-slug"
        assert config["repo_name"] == "real-slug"
        # display_name remains what was specified
        assert config["display_name"] != config["repo_name"]

    def _setup_minimal_repo(self, repo_dir: Path, _repo: str) -> None:
        """Create a minimal checkout skeleton for setup_node."""
        (repo_dir / "scripts").mkdir(parents=True, exist_ok=True)
        (repo_dir / "docs" / "authority").mkdir(parents=True, exist_ok=True)
        (repo_dir / "data" / "federation").mkdir(parents=True, exist_ok=True)
        (repo_dir / ".well-known").mkdir(parents=True, exist_ok=True)

        scripts_dir = repo_dir / "scripts"
        for name in [
            "setup_node.py", "federation_utils.py",
            "render_federation_descriptor.py", "render_agent_card.py",
            "export_authority_feed.py", "discover_federation_peers.py",
        ]:
            src = _SCRIPTS / name
            dest = scripts_dir / name
            if src.exists() and not dest.exists():
                dest.write_text(src.read_text())

        gov_src = _SCRIPTS / "governance"
        gov_dest = scripts_dir / "governance"
        if gov_src.exists() and not gov_dest.exists():
            gov_dest.mkdir(exist_ok=True)
            for gov_file in gov_src.iterdir():
                if gov_file.is_file() and gov_file.suffix == ".py":
                    (gov_dest / gov_file.name).write_text(gov_file.read_text())

        caps_src = _SCRIPTS.parent / "docs" / "authority" / "capabilities.json"
        caps_dest = repo_dir / "docs" / "authority" / "capabilities.json"
        if caps_src.exists():
            caps_dest.write_text(caps_src.read_text())
        else:
            caps_dest.write_text(json.dumps({"skills": []}))

        seeds_src = _SCRIPTS.parent / "data" / "federation" / "authority-descriptor-seeds.json"
        seeds_dest = repo_dir / "data" / "federation" / "authority-descriptor-seeds.json"
        if seeds_src.exists():
            seeds_dest.write_text(seeds_src.read_text())


# ── 9. Blocker behavior tests ───────────────────────────────────────────────


class TestBlocker1NoGuessing:
    """Without git remote and without --repo, setup must fail closed."""

    def _run_non_interactive(
        self, repo_root, **kwargs
    ):
        import subprocess as sp
        scripts_dest = repo_root / "scripts"
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
        args = [sys.executable, str(scripts_dest / "setup_node.py"),
                "--non-interactive"]
        for k, v in kwargs.items():
            args.append(f"--{k.replace('_', '-')}")
            args.append(str(v))
        return sp.run(
            args, capture_output=True, text=True, cwd=str(repo_root),
            env={"PATH": os.environ.get("PATH", ""),
                 "HOME": os.environ.get("HOME", ""),
                 "USER": os.environ.get("USER", ""),
                 "TMPDIR": os.environ.get("TMPDIR", "/tmp")},
        )

    def _setup_skel(self, tmp_path):
        (tmp_path / "docs" / "authority").mkdir(parents=True, exist_ok=True)
        (tmp_path / "data" / "federation").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".well-known").mkdir(parents=True, exist_ok=True)
        caps = tmp_path / "docs" / "authority" / "capabilities.json"
        caps.write_text(json.dumps({"skills": []}))
        seeds = tmp_path / "data" / "federation" / "authority-descriptor-seeds.json"
        seeds.write_text(json.dumps({"descriptor_urls": []}))

    def test_no_remote_no_repo_fails(self, tmp_path):
        """Exit non-zero when identity cannot be determined."""
        self._setup_skel(tmp_path)
        result = self._run_non_interactive(
            tmp_path, name="Test Node", role="relay",
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "cannot determine repository identity" in result.stderr.lower()

    def test_no_remote_no_repo_no_config_file(self, tmp_path):
        """No .federation-setup.json is created on identity failure."""
        self._setup_skel(tmp_path)
        self._run_non_interactive(tmp_path, name="Test Node", role="relay")
        assert not (tmp_path / ".federation-setup.json").exists(), (
            ".federation-setup.json must not be created on identity failure"
        )

    def test_no_remote_no_repo_no_topic_output(self, tmp_path):
        """Topic operation must not appear in output when identity fails."""
        self._setup_skel(tmp_path)
        result = self._run_non_interactive(
            tmp_path, name="Test Node", role="relay",
        )
        assert "agent-federation-node" not in result.stdout, (
            "topic operation must not appear in output"
        )


class TestBlocker2RemoteWriteSafety:
    """--repo without git remote must disable remote writes."""

    def _run_non_interactive(self, repo_root, **kwargs):
        import subprocess as sp
        scripts_dest = repo_root / "scripts"
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
        args = [sys.executable, str(scripts_dest / "setup_node.py"),
                "--non-interactive"]
        for k, v in kwargs.items():
            args.append(f"--{k.replace('_', '-')}")
            args.append(str(v))
        return sp.run(
            args, capture_output=True, text=True, cwd=str(repo_root),
            env={"PATH": os.environ.get("PATH", ""),
                 "HOME": os.environ.get("HOME", ""),
                 "USER": os.environ.get("USER", ""),
                 "TMPDIR": os.environ.get("TMPDIR", "/tmp")},
        )

    def _setup_skel(self, tmp_path):
        (tmp_path / "docs" / "authority").mkdir(parents=True, exist_ok=True)
        (tmp_path / "data" / "federation").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".well-known").mkdir(parents=True, exist_ok=True)
        caps = tmp_path / "docs" / "authority" / "capabilities.json"
        caps.write_text(json.dumps({"skills": []}))
        seeds = tmp_path / "data" / "federation" / "authority-descriptor-seeds.json"
        seeds.write_text(json.dumps({"descriptor_urls": []}))

    def test_repo_without_remote_produces_local_files(self, tmp_path):
        """--repo with no git remote generates local files successfully."""
        self._setup_skel(tmp_path)
        result = self._run_non_interactive(
            tmp_path, name="Test Node", role="relay",
            repo="test-owner/test-node",
        )
        assert result.returncode == 0, (
            f"Expected success (local mode), got {result.returncode}\n"
            f"stderr: {result.stderr}"
        )
        assert (tmp_path / ".federation-setup.json").exists()
        config = json.loads((tmp_path / ".federation-setup.json").read_text())
        assert config["github_repo"] == "test-owner/test-node"
        assert config["display_name"] == "Test Node"

    def test_repo_without_remote_shows_local_mode(self, tmp_path):
        """Output must clearly indicate LOCAL / OFFLINE MODE."""
        self._setup_skel(tmp_path)
        result = self._run_non_interactive(
            tmp_path, name="Test Node", role="relay",
            repo="test-owner/test-node",
        )
        assert "LOCAL" in result.stdout or "OFFLINE" in result.stdout, (
            f"Must show local/offline mode indicator.\nstdout: {result.stdout}"
        )

    def test_repo_without_remote_no_topic_write(self, tmp_path):
        """Topic write must not be attempted in local mode."""
        self._setup_skel(tmp_path)
        result = self._run_non_interactive(
            tmp_path, name="Test Node", role="relay",
            repo="test-owner/test-node",
        )
        assert "Topic (skipped" in result.stdout, (
            f"Topic must be skipped in local mode.\nstdout: {result.stdout}"
        )

    def test_repo_conflicts_with_remote_fails(self, tmp_path):
        """--repo that differs from git remote must fail closed."""
        self._setup_skel(tmp_path)
        # Build a minimal valid git repo so repo_from_git_remote succeeds.
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text(
            '[remote "origin"]\n\turl = https://github.com/real-org/real-repo.git\n'
        )
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
        (git_dir / "objects").mkdir()
        (git_dir / "refs").mkdir()
        (git_dir / "refs" / "heads").mkdir()
        result = self._run_non_interactive(
            tmp_path, name="Test Node", role="relay",
            repo="other-org/other-repo",
        )
        assert result.returncode != 0, (
            f"Must fail when --repo conflicts with remote.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "conflicts" in result.stderr.lower()

    def test_repo_matches_remote_allows_writes(self, tmp_path):
        """--repo that matches git remote allows normal operation."""
        self._setup_skel(tmp_path)
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text(
            '[remote "origin"]\n\turl = https://github.com/match-org/match-repo.git\n'
        )
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
        result = self._run_non_interactive(
            tmp_path, name="Test Node", role="relay",
            repo="match-org/match-repo",
        )
        assert result.returncode == 0, (
            f"Expected success when --repo matches remote.\n"
            f"stderr: {result.stderr}"
        )
        config = json.loads((tmp_path / ".federation-setup.json").read_text())
        assert config["github_repo"] == "match-org/match-repo"


class TestBlocker4ReadmeHonesty:
    """Malformed README markers must not produce false success."""

    def _run_setup(self, repo_root, repo):
        import subprocess as sp
        scripts_dest = repo_root / "scripts"
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
        return sp.run(
            [sys.executable, str(scripts_dest / "setup_node.py"),
             "--non-interactive", "--name", "Test Node", "--role", "relay",
             "--repo", repo, "--org", "dummy"],
            capture_output=True, text=True, cwd=str(repo_root),
        )

    def _setup_skel(self, tmp_path):
        (tmp_path / "docs" / "authority").mkdir(parents=True, exist_ok=True)
        (tmp_path / "data" / "federation").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".well-known").mkdir(parents=True, exist_ok=True)
        caps = tmp_path / "docs" / "authority" / "capabilities.json"
        caps.write_text(json.dumps({"skills": []}))
        seeds = tmp_path / "data" / "federation" / "authority-descriptor-seeds.json"
        seeds.write_text(json.dumps({"descriptor_urls": []}))

    def test_double_begin_no_green_check(self, tmp_path):
        """Double BEGIN markers → malformed, no green check, file unchanged."""
        self._setup_skel(tmp_path)
        readme = tmp_path / "README.md"
        original = (
            "# Test\n\n<!-- BEGIN FEDERATION NODE IDENTITY -->\n"
            "<!-- BEGIN FEDERATION NODE IDENTITY -->\n"
            "> **Node:** Old\n"
            "<!-- END FEDERATION NODE IDENTITY -->\n"
        )
        readme.write_text(original)
        result = self._run_setup(tmp_path, "test-org/test-node")
        assert result.returncode == 0
        assert "✓ README" not in result.stdout, (
            f"Must not show green checkmark for malformed README.\n{result.stdout}"
        )
        assert readme.read_text() == original

    def test_missing_end_no_green_check(self, tmp_path):
        """Missing END marker → malformed, file unchanged."""
        self._setup_skel(tmp_path)
        readme = tmp_path / "README.md"
        original = (
            "# Test\n\n<!-- BEGIN FEDERATION NODE IDENTITY -->\n"
            "> **Node:** Old\n"
        )
        readme.write_text(original)
        result = self._run_setup(tmp_path, "test-org/test-node")
        assert "✓ README" not in result.stdout
        assert readme.read_text() == original

    def test_end_before_begin_no_green_check(self, tmp_path):
        """END before BEGIN → malformed, file unchanged."""
        self._setup_skel(tmp_path)
        readme = tmp_path / "README.md"
        original = (
            "# Test\n\n<!-- END FEDERATION NODE IDENTITY -->\n"
            "garbage\n<!-- BEGIN FEDERATION NODE IDENTITY -->\n"
            "> **Node:** Old\n"
        )
        readme.write_text(original)
        result = self._run_setup(tmp_path, "test-org/test-node")
        assert "✓ README" not in result.stdout
        assert readme.read_text() == original



class TestBlocker5ReadmeWithoutH1:
    """README without H1 heading must still get identity block inserted."""

    def _run_setup(self, repo_root, repo):
        import subprocess as sp
        scripts_dest = repo_root / "scripts"
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
        return sp.run(
            [sys.executable, str(scripts_dest / "setup_node.py"),
             "--non-interactive", "--name", "Proof Node", "--role", "relay",
             "--repo", repo, "--org", "dummy"],
            capture_output=True, text=True, cwd=str(repo_root),
        )

    def _setup_skel(self, tmp_path):
        (tmp_path / "docs" / "authority").mkdir(parents=True, exist_ok=True)
        (tmp_path / "data" / "federation").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".well-known").mkdir(parents=True, exist_ok=True)
        caps = tmp_path / "docs" / "authority" / "capabilities.json"
        caps.write_text(json.dumps({"skills": []}))
        seeds = tmp_path / "data" / "federation" / "authority-descriptor-seeds.json"
        seeds.write_text(json.dumps({"descriptor_urls": []}))

    def test_readme_without_h1_gets_identity_block(self, tmp_path):
        """README with no # heading gets identity block prepended."""
        self._setup_skel(tmp_path)
        readme = tmp_path / "README.md"
        original = "Federation node documentation\n\nCustom text.\n"
        readme.write_text(original)
        result = self._run_setup(tmp_path, "proof-org/proof-node")
        assert result.returncode == 0, (
            f"Setup must succeed.\nstderr: {result.stderr}"
        )
        content = readme.read_text()
        assert content.count("<!-- BEGIN FEDERATION NODE IDENTITY -->") == 1
        assert content.count("<!-- END FEDERATION NODE IDENTITY -->") == 1
        assert "Proof Node" in content
        assert "proof-org/proof-node" in content
        # Original text fully preserved
        assert original in content, (
            f"Original README text must be preserved.\ncontent:\n{content}"
        )
        # Output reports success (check for the status message after ANSI codes)
        assert "README.md (identity block inserted)" in result.stdout or \
               "README.md (identity block updated)" in result.stdout or \
               "README.md (identity block unchanged)" in result.stdout or \
               "README.md (created with identity block)" in result.stdout, (
            f"Must report README success.\nstdout: {result.stdout}"
        )

    def test_empty_readme_gets_identity_block(self, tmp_path):
        """Empty existing README receives the identity block."""
        self._setup_skel(tmp_path)
        readme = tmp_path / "README.md"
        readme.write_text("")
        result = self._run_setup(tmp_path, "proof-org/proof-node")
        assert result.returncode == 0
        content = readme.read_text()
        assert content.count("<!-- BEGIN FEDERATION NODE IDENTITY -->") == 1
        assert content.count("<!-- END FEDERATION NODE IDENTITY -->") == 1
        assert "Proof Node" in content
        assert "proof-org/proof-node" in content
        assert "README.md (identity block inserted)" in result.stdout or \
               "README.md (identity block updated)" in result.stdout or \
               "README.md (identity block unchanged)" in result.stdout or \
               "README.md (created with identity block)" in result.stdout

    def test_readme_with_h1_still_inserts_after_heading(self, tmp_path):
        """README with # heading inserts block after heading, not at top."""
        self._setup_skel(tmp_path)
        readme = tmp_path / "README.md"
        original = "# My Node Title\n\nSome introduction text.\n"
        readme.write_text(original)
        result = self._run_setup(tmp_path, "proof-org/proof-node")
        assert result.returncode == 0
        content = readme.read_text()
        assert content.count("<!-- BEGIN FEDERATION NODE IDENTITY -->") == 1
        assert content.index("# My Node Title") < content.index("<!-- BEGIN FEDERATION NODE IDENTITY -->"), (
            "Identity block must appear after H1 heading."
        )
