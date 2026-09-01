
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

If the engine cannot verify canonical squad state, bank, free transfers, legality, affordability, captain/vice, or the selected optimizer plan, it sends **Recommendation withheld / manual check required** instead of a plausible guess. Public picks do not normally include private purchase/selling-price fields, so managed-squad runs reconstruct the purchase basis from permanent transfer-in costs or the player's season-start price before applying the FPL selling-price rule.

## Timing

The workflow supports an hourly external `workflow_dispatch` heartbeat as the preferred scheduler, while native GitHub Actions cron at minute 17 UTC remains enabled as a backup. Python still decides whether a report is due, so duplicate scheduler wakes do not create duplicate production reports. A ready-to-deploy Cloudflare Cron worker is included in `scheduler/cloudflare/`.

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

## Decision-model guardrails added after GW1 audit

- GW1 legal candidate squads are generated broadly, then reranked by the V3 probabilistic/structural layer using starting-XI value, auto-sub-aware bench value, captaincy, multi-GW utility, and dormant-capital diagnostics.
- LOW-confidence projections are discounted in optimizer ranking; displayed projections remain the raw point estimates.
- Goalkeepers/defenders are not allowed to become balanced-risk captains from a small noisy projection edge.
- All GW1 chips are held by policy; future chip plans are scored on net advantage over an opportunity-cost threshold rather than raw chip-added points.
- Excess GW1 cash above £1.0m is mildly penalized so flexibility does not become unused-budget hoarding.
- GW1 requires at least one high-price MID/FWD captaincy anchor when the player pool contains one, without hard-coding a specific player.


## GW1 robust-market guardrails

When GW1 projections are LOW confidence, the optimizer adds a bounded official-FPL market prior. This is only a balanced-risk sanity input, not the core projection model. Ultra-high-owned premium MID/FWD captain candidates (>=60% ownership, >=£12.0m) require exposure to at least one such asset. Captain and vice-captain both default to MID/FWD unless a defensive asset has a genuinely material robust edge.


## Production uncertainty hardening

- LOW-confidence captaincy uses hysteresis: a high-ownership premium attacker keeps the armband unless another attacker has a meaningful robust edge.
- Expensive attackers are penalized when benched behind marginal starters without a clear projection reason.
- Near-tied optimizer plans (within 0.5 points) are treated as a cluster and receive a small robustness tie-break using captain quality, expected minutes, LOW-confidence exposure and expensive bench usage.
- News research retries up to three times with backoff, records exact exception types/messages, relaxes domain filtering only after curated attempts fail, and marks the email `DEGRADED` if all attempts fail.
- Very low optimizer separation lowers recommendation confidence and is shown explicitly in the email.

## V3 Alpha 3 status

Alpha 3 adds a memoized multi-GW beam search, a probabilistic captain/vice engine, and opportunity-cost treatment for Bench Boost and Triple Captain. The established deterministic optimizer remains the production authority while the multi-GW and new captaincy layers run in shadow mode. See `V3_BUILD_NOTES_ALPHA3.md` for implementation and validation details.

## V3 Alpha 4

Alpha 4 extends the shadow multi-GW planner with chip-state and price-path mechanics:

- Wildcard and Free Hit are native sequential planner actions.
- Free Hit uses a temporary one-week squad and automatically reverts to the permanent squad/value ledger.
- Wildcard creates a permanent new squad while preserving banked free transfers under the current rules model.
- State-dominance pruning removes safely dominated search states before beam truncation.
- Purchase-price ledgers are retained separately from selling prices so projected future selling value follows FPL's profit-sharing rule.
- Optional `price_path` data can make a future transfer genuinely unaffordable after a modeled rise; optional `price_risk` metadata is surfaced as a warning rather than being allowed to dominate expected points.
- Chip squad construction in the shadow planner is dependency-light greedy local search. The established V2 ILP remains the production benchmark until replay/shadow validation justifies promotion.

The multi-GW planner remains disabled by default and runs only when `multigw.enabled` is explicitly enabled.
