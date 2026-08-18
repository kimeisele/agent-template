#!/usr/bin/env python3
"""Attach diff stats and task_solved to the measurement record (P6b).

Reads /tmp/faw-measurement.json (written by the runtime step), fills in the
publish-step facts from the environment, and writes the record under
calibration/runs/<attempt_id>.json in the current directory (the sandbox
checkout).

Env: CAL_CHANGED, CAL_INS, CAL_DEL, CAL_SOLVED, CAL_AID
"""

import json
import os
import pathlib


def main() -> None:
    src = pathlib.Path("/tmp/faw-measurement.json")
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
    rec["task_solved"] = os.environ.get("CAL_SOLVED", "0") == "1"
    attempt = os.environ.get("CAL_AID", "unknown")
    out = pathlib.Path("calibration/runs") / f"{attempt}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=2))
    print(f"measurement attached: {out}", flush=True)


if __name__ == "__main__":
    main()
