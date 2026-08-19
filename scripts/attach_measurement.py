#!/usr/bin/env python3
"""Attach diff stats, acceptance verdict, and extraneous artifacts to the
measurement record (P6b).

Reads /tmp/faw-measurement.json (runtime step) and /tmp/faw-acceptance.json
(acceptance step), merges them, and writes the record under
calibration/runs/<attempt_id>.json in the current directory (sandbox checkout).

Env: CAL_CHANGED, CAL_INS, CAL_DEL, CAL_AID
"""

import json
import os
import pathlib


def main() -> None:
    src = pathlib.Path("/tmp/faw-measurement.json")
    acc = pathlib.Path("/tmp/faw-acceptance.json")
    if not src.is_file():
        print("no measurement file; nothing to attach", flush=True)
        return
    rec = json.loads(src.read_text())
    rec["actions_minutes"] = 0.0
    rec["diff_stats"] = {
        "files_changed": int(os.environ.get("CAL_CHANGED", "0")),
        "insertions": int(os.environ.get("CAL_INS", "0")),
        "deletions": int(os.environ.get("CAL_DEL", "0")),
    }
    if acc.is_file():
        verdict = json.loads(acc.read_text())
        rec["task_solved"] = bool(verdict.get("task_solved"))
        rec["acceptance_source"] = verdict.get("source")
        rec["violations"] = verdict.get("violations", [])
        rec["extraneous_files"] = verdict.get("extraneous_files", [])
        if verdict.get("violations"):
            rec["status"] = "failed"
    else:
        rec["task_solved"] = False
        rec["acceptance_source"] = "missing_acceptance_check"
        rec["violations"] = ["acceptance check did not run"]
        rec["extraneous_files"] = []
    attempt = os.environ.get("CAL_AID", "unknown")
    out = pathlib.Path("calibration/runs") / f"{attempt}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=2))
    print(f"measurement attached: {out}", flush=True)
    print(f"task_solved={rec['task_solved']} status={rec['status']}", flush=True)


if __name__ == "__main__":
    main()
