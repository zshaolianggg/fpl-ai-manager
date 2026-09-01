# V3 Alpha 4 post3 — Runtime reliability hotfix

Version: `3.0.0a4.post3`

## Why this patch exists

The first managed-squad/manual run exceeded the GitHub Actions 25-minute job limit. Two independent runtime hazards were identified:

1. The GW2+ legacy managed optimizer expanded a large beam across multiple transfer depths and could recompute tens of thousands of multi-horizon lineups.
2. Optional bulk FPL enrichment (candidate element summaries and Elite manager history/picks) could make hundreds of requests with long per-request retries under rate limiting.

Neither optional enrichment nor an exhaustive near-tie search should be allowed to prevent delivery of the core recommendation.

## Changes

### Bounded managed optimizer

- Managed optimizer wall-clock budget: 180 seconds.
- Candidate pool reduced from 22 to 14 per position.
- Beam width reduced from 120 to 45.
- Maximum transfer depth reduced from 4 to 3.
- At most 10 pre-ranked incoming replacements are fully evaluated per outgoing player.
- At most 3,000 full plan evaluations per transfer depth.
- When a cap is reached, the best legal plans already evaluated are returned.
- GitHub log now prints optimizer state count and elapsed time.

### Bounded optional FPL enrichment

- Bulk FPL requests use a 6-second timeout and one attempt.
- Candidate summaries have a 60-second wall-clock budget and continue with partial data.
- Elite cohort refresh has a 75-second budget and preserves a cached cohort when refresh cannot finish.
- Elite ownership/captain signal has a 60-second total budget and may return partial observations.
- Optional timeouts produce warnings rather than withholding the FPL recommendation.

### OpenAI/runtime guardrails

- Final OpenAI adjudication has an explicit 90-second timeout.
- Total intended manager runtime budget is 15 minutes.
- If too little runtime remains for the final AI tie-break, deterministic optimizer rank #1 is selected so delivery can still complete.
- Every major stage emits start/end timing notices to GitHub Actions.

### Workflow guardrail

- The recommendation step itself has a 20-minute timeout inside the 25-minute job, leaving time for the `always()` state/cache save step.

## Expected GitHub diagnostics

A full run now emits entries such as:

```text
FPL stage start: candidate_summaries
FPL stage end: candidate_summaries elapsed=...s
FPL stage start: optimizer
Managed optimizer evaluated ... transfer states in ...s
FPL stage end: optimizer elapsed=...s
FPL stage start: elite_discovery
...
```

If an optional stage is degraded, the warning states exactly which runtime budget was exhausted.

## Tests

- `49 passed` with `PYTHONPATH=src pytest -q`.
- Full source/test tree compiles successfully.

## Operational recommendation

Run one forced manual preview after deploying post3. If it is still slow, the new stage timers will identify the exact remaining bottleneck rather than ending with only a generic 25-minute timeout.
