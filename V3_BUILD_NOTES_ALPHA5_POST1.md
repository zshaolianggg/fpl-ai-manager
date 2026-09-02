# V3 Alpha 5 post1 — Runtime and adjudication hardening

Version: `3.0.0a5.post1`

This hotfix addresses the live GW3 run where news research consumed ~324s, the managed optimizer exhausted its 180s budget, WC/FH shadow work consumed ~158s, and the final OpenAI adjudication failed with `context_length_exceeded`.

## 1. Bounded OpenAI adjudication packet

The final LLM no longer receives the full evidence payload. `ai.compact_payload()` sends only:

- top 8 production optimizer plans,
- up to 40 relevant compact player projections,
- up to 3 compact V3 shadow paths,
- up to 16 material news items,
- compact captaincy / Elite / chip / decision-audit fields,
- minimal manager state needed for adjudication.

Large `metrics.lineups`, rich per-GW projection component dictionaries, full snapshots, and other audit-only evidence stay in the evidence/backtest artifacts and are not sent to the model.

The workflow logs `OpenAI adjudication compact input chars=...` so request growth is visible.

## 2. OpenAI fail-soft fallback

OpenAI is a tie-break/adjudication layer, not the legality/optimization authority. If the Responses API fails because of context, timeout, transient API issues, package availability, or another exception, the manager now:

1. logs a warning,
2. selects deterministic optimizer rank #1,
3. optionally exposes rank #2 as the alternative,
4. continues validation/rendering/email delivery.

The workflow no longer dies solely because the optional AI adjudicator is unavailable.

OpenAI SDK retries are disabled for this final call (`max_retries=0`) so a failed optional adjudication cannot consume several hidden retry windows.

## 3. News runtime tightened

The previous news helper hard-coded three attempts and allowed the OpenAI SDK's own retries on top of those attempts. That explains why a nominal 35s timeout could produce a ~324s stage.

New defaults:

- research at most 20 relevant players,
- 2 explicit attempts,
- 25s per attempt,
- OpenAI SDK retries disabled.

News remains fail-soft: degraded news lowers confidence but does not stop the core optimizer.

## 4. Managed optimizer runtime tightened

Previous live run: ~180s internal optimizer budget and ~225s combined optimizer stage.

New managed defaults:

- runtime budget: 75s,
- candidate players per position: 12,
- beam width: 35,
- incoming replacements per outgoing player: 8,
- max full evaluations per depth: 1,400.

The V3 multi-GW shadow planner is now logged as a separate stage and is capped at 25s. This makes runtime attribution clear and prevents its cost from being hidden inside the production optimizer stage.

## 5. WC/FH shadow runtime bounded

WC/FH remain shadow-only. Their comparison is now reduced to:

- 2-GW horizon,
- smaller candidate/beam pools,
- 10s baseline/continuation planner budget,
- 7s direct chip-squad constructor budget,
- 35s total shadow budget.

The direct greedy chip constructor itself now accepts a hard runtime budget. Remaining WC/FH budget is dynamically split between direct construction and continuation search.

## 6. Overall runtime target

Internal total budget reduced from 900s to 720s. The expensive optional stages should now normally remain roughly within:

- news: <= ~50–55s,
- production optimizer: <= ~75s,
- V3 multi-GW shadow: <= ~25s,
- WC/FH shadow: <= ~35s,
- final OpenAI adjudication: <= 60s, with deterministic fallback.

These are safety ceilings, not targets; normal runs should often be much faster.

## Validation

- `60 passed`
- Python source/tests/scripts compile cleanly.
- Added regression tests for bounded adjudication payload and deterministic fallback when OpenAI fails.
