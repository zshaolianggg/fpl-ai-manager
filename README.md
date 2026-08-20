
# FPL AI Manager v2

A safety-first, evidence-driven automated FPL manager for team **6000549**.

## What changed in v2

The old version let the LLM do too much. v2 deliberately separates responsibilities:

1. **Official FPL state is canonical** after every deadline.
2. **Free-transfer state is reconstructed** from public history; failure withholds transfers.
3. **Expected minutes are deterministic**, using recent minutes/starts, status, congestion and structured fresh news.
4. **Player projections are component-based** and Gameweek-aware, so blanks/doubles are handled as Gameweeks rather than "next fixtures".
5. **Free public underlying stats are optional** through a pluggable Understat provider; failure falls back to FPL data.
6. **Python generates legal plans**. OpenAI may only choose a `plan_id`.
7. **Python validates the chosen plan again** before email.
8. **Elite-manager behavior is a bounded sanity/risk signal**, not the projection engine.
9. **Chip opportunities inspect confirmed future fixture structure** and never invent a speculative rearrangement.
10. Every actionable email attaches:
   - `openai-prompt.txt`
   - `evidence-pack.json`
   - `optimizer-plans.csv`

## Recommendation hierarchy

- Your verified team / bank / FT / chip state
- Deterministic 1/3/6-GW projections (45% / 35% / 20%)
- Legal optimizer plans
- Fresh curated news and expected-minutes risk
- Elite-manager sanity/risk signal
- AI adjudication among already-valid plans
- Deterministic post-AI validation

## Elite cohort

The engine targets ~100 historically strong managers and ~75 qualified current-season managers.

Current-season weight inside the **elite layer only**:
- GW1–5: 0%
- GW6–7: 20%
- GW8–9: 30%
- GW10–11: 50%
- GW12–13: 60%
- GW14+: 80%

The historic cohort retains the remainder.

## Safety behavior

If the engine cannot verify canonical squad state, bank, free transfers, selling values, legality, affordability, captain/vice, or the selected optimizer plan, it sends **Recommendation withheld / manual check required** instead of a plausible guess.

## Timing

GitHub Actions wakes hourly at minute 17 UTC. Python decides whether a report is due.

- Preview: ~24h before deadline
- Final: ~2–3.5h before deadline
- If that falls overnight Beijing time, target ~22:00 the previous evening
- Hard sleep-safe cutoff: 23:00 Beijing

## GitHub secrets

Required:
- `OPENAI_API_KEY`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_USE_TLS`
- `EMAIL_FROM`
- `EMAIL_TO`

Optional repository variable:
- `OPENAI_MODEL` (defaults to `gpt-5`)

## Manual test

Actions → FPL AI Manager → Run workflow → choose `preview` or `final`.

## Free/open data policy

No paid football-statistics or projection provider is required.

Mandatory source:
- official public FPL endpoints

Optional free source:
- Understat EPL player xG/xA data, cached locally

If Understat parsing/network access fails, the report continues with FPL-only projections and lowers evidence confidence.

## Known limitations

- Public FPL picks are only authoritative after a deadline. This matches the intended workflow: do not make private transfers before receiving the recommendation.
- Understat is a public web source, not a guaranteed API contract; it is isolated behind a provider/fallback layer.
- Expected-points models are estimates, not guarantees.
- The historical elite cohort is discovered from a broad current Overall candidate pool and then scored entirely on past-season history. It is cached and refreshed every four GWs; it is not a perfect registry of every historically elite manager.
- The v2 chip module is conservative: confirmed blanks/doubles are trusted; unconfirmed future rescheduling is not guessed.

## Tests

Run:

```bash
python -m unittest discover -s tests -v
```

## Test-run isolation

A manual `workflow_dispatch` run with `preview` or `final` is treated as **forced/test delivery**.
It sends the email but does **not** mark the production preview/final as already sent, so testing cannot suppress the later scheduled report.

The persistent `.state` / `.cache` GitHub cache is only saved on due report runs, not on every hourly wake-up.


## Runtime safeguards

GW1 skips elite-manager cohort discovery and per-player current-season history calls because there are no locked elite picks or current-season player histories to use before the first deadline.

From GW2 onward, player-history enrichment is capped to a compact candidate set, elite discovery uses a bounded candidate pool and cached cohorts, and optional evidence should degrade gracefully rather than blocking the recommendation.
