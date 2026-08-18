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
| _(to fill after runs)_ | | | | | | |
