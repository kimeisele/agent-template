"""S8 target-allowlist tests: default-deny, not default-allow."""

from pathlib import Path

import pytest

from agent_runtime.target_allowlist import TargetAllowlist

FIXTURE = """\
allowed_targets:
  - repository: kimeisele/federation-sandbox
    paths:
      - "."
    branch_patterns:
      - "faw/attempt/*"
  - repository: kimeisele/faw-nadi-live-relay
    paths:
      - "nadi/"
    branch_patterns:
      - "faw/attempt/*"
"""


@pytest.fixture
def allowlist(tmp_path: Path) -> TargetAllowlist:
    p = tmp_path / "allowlist.yaml"
    p.write_text(FIXTURE, encoding="utf-8")
    return TargetAllowlist.from_file(p)


def test_allowed_target_passes(allowlist: TargetAllowlist):
    assert allowlist.allows(
        repository="kimeisele/federation-sandbox",
        path=".",
        branch="faw/attempt/wo-1",
    )
    assert allowlist.allows(
        repository="kimeisele/faw-nadi-live-relay",
        path="nadi/",
        branch="faw/attempt/wo-2",
    )


def test_unknown_repository_rejected(allowlist: TargetAllowlist):
    assert not allowlist.allows(
        repository="kimeisele/somewhere-else",
        path=".",
        branch="faw/attempt/wo-3",
    )


def test_main_branch_rejected(allowlist: TargetAllowlist):
    # The runtime must never write `main` (D1/S4).
    assert not allowlist.allows(
        repository="kimeisele/federation-sandbox",
        path=".",
        branch="main",
    )


def test_non_matching_branch_rejected(allowlist: TargetAllowlist):
    assert not allowlist.allows(
        repository="kimeisele/federation-sandbox",
        path=".",
        branch="feature/x",
    )


def test_path_outside_allowance_rejected(allowlist: TargetAllowlist):
    # relay only allows nadi/ — a write outside it must be denied
    assert not allowlist.allows(
        repository="kimeisele/faw-nadi-live-relay",
        path="other/",
        branch="faw/attempt/wo-4",
    )


def test_empty_allowlist_denies_everything(tmp_path: Path):
    p = tmp_path / "empty.yaml"
    p.write_text("allowed_targets: []\n", encoding="utf-8")
    allowlist = TargetAllowlist.from_file(p)
    assert not allowlist.allows(
        repository="kimeisele/federation-sandbox",
        path=".",
        branch="faw/attempt/wo-5",
    )


def test_missing_allowlist_denies_everything(tmp_path: Path):
    allowlist = TargetAllowlist.from_file(tmp_path / "does-not-exist.yaml")
    assert not allowlist.allows(
        repository="kimeisele/federation-sandbox",
        path=".",
        branch="faw/attempt/wo-6",
    )


def test_default_constructor_denies_everything():
    allowlist = TargetAllowlist()
    assert not allowlist.allows(
        repository="kimeisele/federation-sandbox",
        path=".",
        branch="faw/attempt/wo-7",
    )
