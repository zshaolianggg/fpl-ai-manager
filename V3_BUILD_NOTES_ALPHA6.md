# FPL AI Manager V3 Alpha 6

Version: `3.0.0a6`

## Purpose

Alpha 6 removes the LLM from the production decision path. The numerical/strategy engine now selects the recommendation deterministically; AI is an optional, low-cost explanation layer only.

## Production decision authority

The production sequence is now:

1. official/public FPL state reconstruction
2. projections and minutes/news evidence
3. production optimizer + near-tie robustness/flexibility sorting
4. deterministic plan selection
5. deterministic legality/affordability/lineup validation
6. optional AI explanation of the already-final decision
7. report/email delivery

The explanation model cannot return a `plan_id`, transfers, captain, chip or any other action field. Its strict output schema contains prose fields only.

## Credit/runtime reduction

`config/manager.json` now has:

```json
"ai": {
  "decision_authority": false,
  "explanation_enabled": true,
  "explanation_mode": "complex_only",
  "explanation_model": "gpt-5-mini",
  "explanation_timeout_seconds": 25
}
```

`complex_only` means the AI explanation is requested only when at least one of these is true:

- the top plans are inside the equivalence band;
- V2 and V3 recommend different first routes;
- material HIGH/MEDIUM news affects the decision;
- the selected move takes a hit;
- a production chip is selected.

A clear, routine week is explained deterministically with no model call.

The AI packet contains only the already-final plan, one close alternative, named transfer signals, compact V2/V3 comparison, a few material news items and minimal chip diagnostics. It does not receive the full projection/evidence pack.

`OPENAI_EXPLANATION_MODEL` may override the explanation model independently from any other OpenAI use. `.env.example` defaults it to `gpt-5-mini`.

## Better audit output

Reports now explicitly show:

- `Decision authority: DETERMINISTIC (AI cannot change the plan)`;
- named V2 production transfer route;
- named V3 shadow first route;
- up to two V3 future continuation steps;
- V3 captaincy shadow candidate/utility information;
- transfer-signal strength across the top plans;
- whether AI explanation was used.

This avoids raw FPL element IDs leaking into prose and makes disagreements auditable without relying on an LLM.

## Transfer signal strength

Alpha 6 summarizes recurring moves across the strongest plans. It distinguishes:

- how often a player is sold (`sell strength`), and
- how often a particular replacement is chosen (`replacement strength`).

This lets the report say, for example, that selling a player is STRONG while choosing Egan over Hall is only WEAK/MODERATE.

## V2/V3 comparison

The comparison object now stores a compact sequence of V3 future steps. This makes it possible to show not just that V3 differs from V2, but what the V3 route is trying to enable in later gameweeks.

V3 remains shadow-only in Alpha 6.

## Backtesting

Snapshots/evidence now store the deterministic selected plan and decision metadata. This keeps replay results reproducible: identical inputs produce the same production action regardless of LLM availability.

## Reliability

AI explanation failure is completely non-fatal. The deterministic report is still rendered and emailed.

All Alpha 5 runtime safeguards remain in place, including bounded news research, optimizer runtime budgets, bounded V3 shadow search and bounded WC/FH shadow analysis.

## Tests

Alpha 6 adds tests proving that:

- deterministic selection always uses the already-sorted production plan;
- complex-only explanation triggering works;
- explanation packets use player names and remain decision-free;
- sell consensus can be strong while an individual replacement signal is weak.

Full regression result: **64 passed**.

Source, tests and scripts compile successfully.
