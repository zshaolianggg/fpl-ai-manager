# V3 Alpha 4 post4 — WC/FH production safety patch

## Why this patch exists

A GW3 preview recommended an early Wildcard from a comparison that overstated chip value by measuring the rebuilt squad mainly against a static/no-action baseline. That is not the right strategic question. Wildcard and Free Hit should be compared with the best legal non-chip transfer path over multiple gameweeks and must include the option value of preserving the chip.

## Production authority change

- Wildcard and Free Hit are now **shadow-only**.
- They are never added to `optimizer_plans` when `chips.production_wildcard_freehit=false` (the default).
- Because the final AI adjudicator must choose from `optimizer_plans`, it cannot activate WC/FH.
- Bench Boost and Triple Captain retain their existing opportunity-cost production logic.

## New sequential chip comparison

For managed squads, a bounded shadow evaluator now runs:

1. best non-chip multi-GW path;
2. forced Wildcard-now path;
3. forced Free-Hit-now path.

It reports, for each chip:

- chip-path sequential score;
- gross advantage versus the **best non-chip sequential path**;
- explicit preservation reserve;
- net opportunity edge;
- confidence/news gate result;
- planner runtime diagnostics.

This evidence is advisory only and cannot change the production recommendation.

## Conservative gates

The shadow evaluator marks promotion eligibility false when all current-squad projections are LOW confidence. DEGRADED news also blocks the confidence gate unless the permanent squad has at least two sub-45 expected-minute players. Even if the gate passes, this build still keeps WC/FH shadow-only.

Default bounded settings:

- 3-GW planning horizon
- 5 structural candidates per position
- beam width 25
- max 2 transfers/GW
- 20-second budget per shadow run
- minimum Wildcard preservation reserve: 10 points
- minimum Free Hit preservation reserve: 8 points
- minimum net opportunity edge: 4 points
- LOW-confidence edge multiplier: 1.5x

## Runtime safety

`plan_multigw` now accepts:

- `force_first_chip`
- `runtime_budget_seconds`

This lets the chip audit explicitly ask “what if WC/FH is used now?” without an unbounded search.

## Reporting

Reports now show:

- WC/FH production authority in the Decision Engine Audit;
- an advisory-only Wildcard / Free Hit shadow comparison;
- best non-chip sequential baseline;
- gross edge, preservation reserve, net edge and confidence/news gate.

The OpenAI system instruction explicitly forbids recommending or describing WC/FH as a production action in this build.

## Tests

`51 passed`.

New regression coverage verifies:

- a forced Free Hit shadow path really begins with Free Hit;
- WC/FH cannot enter the production plan list while shadow-only mode is active.

The full source/test tree compiles successfully.
