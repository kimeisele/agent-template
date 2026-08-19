#!/usr/bin/env python3
"""Task-bound acceptance check (PROGRAM 6b, task_solved).

The delegation carries an explicit, checkable acceptance criterion; the
workflow (or any reviewer) validates AGAINST that criterion. Without a
criterion, task_solved is false (fail closed, like the allowlist).

Delegation acceptance shape:
    "acceptance": {
        "expected_changes": [            # each must be satisfied
            {"path": "x.py", "contains": ["def f", "\"\"\""]},
            {"path": "y.py", "contains": ["MULTIPLIER"]}
        ],
        "forbidden_paths": [             # if any appears -> extraneous
            "test_decorator", "x.py.backup", "__pycache__", "*.pyc"
        ]
    }

Env: FAW_DELEGATION_FILE, FAW_CHECKOUT (sandbox workdir).
Writes the acceptance verdict to /tmp/faw-acceptance.json.
"""

import json
import os
import pathlib
import fnmatch


def _expected_violations(checkout: pathlib.Path, expected_changes) -> list[str]:
    violations = []
    for req in expected_changes or []:
        path = checkout / req.get("path", "")
        if not path.is_file():
            violations.append(f"missing expected change file: {req.get('path')}")
            continue
        content = path.read_text(errors="replace")
        for needle in req.get("contains", []):
            if needle not in content:
                violations.append(f"{req.get('path')} does not contain {needle!r}")
    return violations


def _extraneous_files(checkout: pathlib.Path, forbidden_paths, allowed_expected_paths) -> list[str]:
    """List files changed by the runtime that are not expected or are forbidden."""
    # Determine the set of runtime-touched files vs the base (main HEAD).
    base_head = checkout / ".git"
    # Simpler signal: forbidden patterns present in the checkout tree.
    extraneous = []
    for root, _dirs, files in os.walk(checkout):
        for name in files:
            rel = pathlib.Path(root).relative_to(checkout)
            relpath = str(rel / name) if str(rel) != "." else name
            for pat in forbidden_paths or []:
                if fnmatch.fnmatch(relpath, pat) or fnmatch.fnmatch(name, pat):
                    extraneous.append(relpath)
    return sorted(set(extraneous))


def main() -> None:
    delegation_file = os.environ.get("FAW_DELEGATION_FILE")
    checkout = pathlib.Path(os.environ.get("FAW_CHECKOUT", "/tmp/sandbox-work"))
    if not delegation_file or not pathlib.Path(delegation_file).is_file():
        print("no delegation file; acceptance unknown (fail closed)", flush=True)
        _write({"task_solved": False, "source": "no_delegation", "violations": [], "extraneous": []})
        return

    delegation = json.loads(pathlib.Path(delegation_file).read_text())
    acceptance = delegation.get("acceptance")
    if not isinstance(acceptance, dict):
        print("delegation has no acceptance criterion; task_solved = false (fail closed)", flush=True)
        _write({"task_solved": False, "source": "no_acceptance", "violations": [], "extraneous": []})
        return

    expected = acceptance.get("expected_changes") or []
    forbidden = acceptance.get("forbidden_paths") or []
    violations = _expected_violations(checkout, expected)
    extraneous = _extraneous_files(checkout, forbidden, [e.get("path") for e in expected])
    solved = not violations

    verdict = {
        "task_solved": solved,
        "source": "delegation_acceptance",
        "expected_changes": expected,
        "violations": violations,
        "extraneous_files": extraneous,
        "checkout": str(checkout),
    }
    _write(verdict)
    print(f"task_solved={solved} violations={violations} extraneous={extraneous}", flush=True)


def _write(verdict: dict) -> None:
    out = pathlib.Path("/tmp/faw-acceptance.json")
    out.write_text(json.dumps(verdict, indent=2))
    # also print for visibility
    print(json.dumps(verdict, indent=2), flush=True)


if __name__ == "__main__":
    main()
