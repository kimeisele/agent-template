# FAW Calibration (PROGRAM 6b)

Measurement series for the vertical E2E proof. Each attempt produces one
measurement record at `calibration/runs/<attempt_id>.json`, validated
against `calibration/measurement.schema.json`.

## Rules (from the program brief §9 6b, D5)

- **The measurement schema is committed before any run.** It defines what
  "measured" means so the series is comparable.
- **Cost/token claims are either measured or omitted** (D5). The runtime
  reports wall seconds and output bytes only; provider token/cost numbers
  are included **only** if the runtime events expose them, and are marked
  `source` accordingly. Never asserted unverified.
- **Token measurement: [UNBEKANNT — not available from the runtime path.]**
  openhands' MessageEvent payloads carry an empty `usage` object; the token
  numbers seen in the workflow log come from the LLM probe (a direct curl to
  the OpenAI-compatible endpoint), not from openhands' events. So
  `provider_usage` stays `null` with `source: "unknown"`. Provider-side token
  accounting for per-attempt attribution is an open item (PROGRAM 6b).
- **A green run without the bounded change is NOT a success.** `task_solved`
  is false unless the docstring is present on the result branch.
- Branches `faw/attempt/<id>` are kept as evidence. Cleanup command:

```bash
# delete one stale attempt branch (manual, evidence is gone afterwards)
gh api -X DELETE repos/kimeisele/federation-sandbox/git/refs/heads/faw/attempt/<id>
```

## Series

| attempt_id | run_id | wall_seconds | events | status | task_solved | notes |
|---|---|---|---|---|---|---|
| live-1 | 32216381919 | 59.4 | 13 | succeeded | true | |
| live-2 | 32216386414 | 56.6 | 15 | succeeded | true | |
| live-3 | 32216390719 | 93.8 | 17 | succeeded | true | slowest (2.7x vs live-10) |
| live-4 | 32216394909 | 50.8 | 11 | succeeded | true | |
| live-5 | 32216702074 | 66.9 | 15 | succeeded | true | rerun after branch-conflict cleanup |
| live-6 | 32216404317 | 48.5 | 11 | succeeded | true | |
| live-7 | 32216409012 | 52.3 | 17 | succeeded | true | |
| live-8 | 32216413078 | 42.0 | 11 | succeeded | true | |
| live-9 | 32216417997 | 45.2 | 13 | succeeded | true | |
| live-10 | 32216422038 | 34.3 | 9 | succeeded | true | fastest |

**Summary (10 runs):** mean wall 55.0s (median 51.5s, stdev 16.5s, range
34.3–93.8s); events mean 13.2 (range 9–17); **task_solved 10/10** — every
run applied the docstring. Provider token/cost: not measurable from the
runtime events (`provider_usage` null, `source` unknown — D5). One initial
run (live-5, first dispatch) failed on a stale-branch push conflict; rerun
after cleanup succeeded.
