# FPL AI Manager V3 Alpha 5 — Validation & Promotion

Version: `3.0.0a5`

Alpha 5 deliberately focuses on correctness and measurement rather than adding another broad decision feature.

## 1. Auto-sub valuation correctness

The fixture projection `per_gw` value is already unconditional: zero-minute outcomes are included. Alpha 5 therefore does **not** multiply the whole projection by appearance probability a second time. Instead it makes the identity explicit:

`P(appearance) × E[points | appearance] = unconditional expected points`.

The actual correctness improvement is that formation-legality weighting now uses the **position-specific no-show probabilities of the starting XI** instead of averaging all starters equally. A bench midfielder is therefore not treated as equally useful when the actual absence risk is concentrated in defenders, and vice versa.

New regression tests cover zero-appearance bench players and prevent double-discounting.

## 2. Historical/live replay framework

New package:

- `src/fpl_ai_manager/backtest/snapshots.py`
- `src/fpl_ai_manager/backtest/replay.py`
- `src/fpl_ai_manager/backtest/metrics.py`
- `scripts/backtest_replay.py`

Every due recommendation attempts to persist a frozen pre-deadline snapshot under `.state/backtest/`. The snapshot includes canonical state, player/projection data, config, V2 candidate plans, V3 shadow paths, the V2/V3 comparison, and timestamped evidence metadata.

The replay path performs **no network access**. A leakage guard rejects evidence timestamped after the recorded FPL deadline. This is the foundation for accumulating real GW-by-GW V2 vs V3 evidence and later adding historical archives.

Example:

```bash
PYTHONPATH=src python scripts/backtest_replay.py .state/backtest/gw3-preview.json
```

The framework currently replays frozen snapshots; it does not ship a historical Opta/FPL data archive.

## 3. V2 vs V3 is now first-class

The multi-GW planner runs as a bounded shadow comparison whenever `multigw.shadow_mode` is enabled. It is limited to 45 seconds by default and runs with `include_chips=false` so the comparison is apples-to-apples with normal production transfer/ROLL decisions.

The evidence/report now records:

- V2 first action
- V3 first action
- `AGREE`, `DIFFERENT_ROUTE`, or `MATERIAL_DISAGREEMENT`
- V3 path diagnostics

V2 remains production authority in Alpha 5.

## 4. Near-tie equivalence policy

The near-tie band is widened to `0.75` points. Plans inside it are treated as statistically equivalent rather than ranked by false decimal precision.

Within that band, a secondary tie-break favors:

- secure minutes / captaincy structure
- usable bank/flexibility
- avoiding hits
- avoiding unnecessary transfer churn
- avoiding expensive deep-bench capital

Outside the band, raw optimizer score remains primary.

## 5. Wildcard / Free Hit shadow construction repaired

Alpha 4 forced the normal beam search to discover a WC/FH action, which could return `No legal forced-chip shadow path found within budget` even when legal squads clearly existed.

Alpha 5 instead:

1. constructs the chip squad directly with the structural candidate pool;
2. applies WC/FH state mechanics explicitly;
3. scores the current chip GW;
4. continues the remaining horizon through the normal no-chip sequential planner;
5. compares that path with the best non-chip multi-GW path.

WC/FH remain **shadow-only** and cannot enter production optimizer plans.

## Runtime / safety

- V3 normal-transfer shadow runtime: 45s.
- WC/FH direct shadow runs remain separately bounded.
- Production V2 fail-soft runtime protections from post3 remain intact.
- Backtest snapshot failures are non-blocking and become warnings.

## Validation

`58` dependency-light regression tests pass, including new Alpha 5 tests for:

- auto-sub appearance accounting;
- position-weighted bench legality;
- near-tie flexibility selection;
- V2/V3 disagreement labeling;
- future-evidence leakage rejection;
- direct Free Hit shadow construction.

The full `src/` and `tests/` trees compile successfully.
