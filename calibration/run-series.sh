#!/usr/bin/env bash
# calibration/run-series.sh — drive the FAW calibration series (PROGRAM 6b).
#
# Fires N workflow_dispatch runs with consistent attempt ids (live-1..live-N),
# then waits for each to finish and prints the measurement per run.
#
# Usage:
#   bash calibration/run-series.sh [N]     # default 10
#
# Prereqs: gh authenticated; the FAW Attempt workflow merged; sandbox repo
# reachable; LLM/App secrets set in agent-template.
#
# Branches faw/attempt/live-N are KEPT as evidence. To remove one:
#   gh api -X DELETE repos/kimeisele/federation-sandbox/git/refs/heads/faw/attempt/live-<N>

set -uo pipefail
N="${1:-10}"
REPO="kimeisele/agent-template"
SANDBOX="kimeisele/federation-sandbox"

echo "=== FAW calibration series: $N runs ==="
for i in $(seq 1 "$N"); do
  AID="live-$i"
  echo "--- dispatching $AID ---"
  gh workflow run "FAW Attempt" --repo "$REPO" \
    -f delegation_file=.fixtures/delegation-test.jsonl \
    -f attempt_id="$AID"
done

echo "=== waiting for runs and collecting measurements ==="
for i in $(seq 1 "$N"); do
  AID="live-$i"
  # Wait for a completed run whose inputs match this attempt id.
  RUN=""
  for _ in $(seq 1 60); do
    RUN="$(gh run list --repo "$REPO" --workflow "FAW Attempt" --limit 30 \
      --json databaseId,displayTitle,status,conclusion \
      --jq "[.[] | select(.displayTitle | contains(\"$AID\")) | select(.status==\"completed\")][0].databaseId // empty")"
    [ -n "$RUN" ] && break
    sleep 10
  done
  if [ -z "$RUN" ]; then
    echo "$AID: TIMEOUT waiting for run"
    continue
  fi
  echo "$AID: run=$RUN conclusion=$(gh run view "$RUN" --repo "$REPO" --json conclusion --jq .conclusion)"
  # The measurement record is committed on the sandbox branch by the workflow.
  gh api "repos/$SANDBOX/contents/calibration/runs/$AID.json?ref=faw/attempt/$AID" \
    --jq '.content' 2>/dev/null | base64 -d 2>/dev/null | python3 -m json.tool 2>/dev/null \
    || echo "$AID: no measurement record on branch (run failed before publish)"
done
echo "=== series complete ==="
