# FPL AI Manager V3 Alpha 4 Build Notes

Version: `3.0.0a4`

## What changed

### 1. Wildcard and Free Hit are real multi-GW actions
`ManagerState` now carries Wildcard and Free Hit availability. The planner can branch into either chip when available.

- **Free Hit**: builds a temporary legal 15-player squad for the current GW, scores that squad, then advances to the next GW with the original permanent squad, bank and purchase-price ledger restored. The Free Hit is marked spent.
- **Wildcard**: builds a legal long-horizon squad, applies the squad permanently, recalculates bank from actual selling proceeds and incoming modeled prices, and marks the Wildcard spent.
- Both chip transitions preserve banked free transfers and apply the normal next-GW accrual in the current rules model.

Alpha 4 uses dependency-light greedy local search for chip squads so the shadow planner does not depend on PuLP. This is intentionally a candidate generator, not a claim of global chip-squad optimality.

### 2. State-dominance pruning
Before beam truncation, planner states with identical football/value ledgers and chip availability are compared. A state is removed only when another state has at least as much accumulated score, bank and free transfers, with a strict advantage in at least one dimension.

The diagnostic payload now includes `dominance_pruned`.

### 3. Price-path aware transfer ledger
New `prices.py` adds:

- `projected_price(row, gw)` — consumes optional future `price_path` entries and otherwise falls back to the current official price.
- `projected_sell_price(...)` — applies the FPL profit-sharing selling rule to modeled future prices.
- optional bounded `price_risk` metadata for transparent affordability warnings.

`ManagerState` now keeps **purchase prices separately from selling prices**. This is required to model future selling value correctly after price changes.

A future price rise can therefore make a delayed transfer unaffordable in the search. Alpha 4 does **not** invent price forecasts; if no `price_path` is supplied, prices remain flat.

### 4. Affordability risk is informational, not a football override
Optional price-risk metadata can flag that a zero-bank purchase path is exposed to a likely rise. That risk is attached to planner steps but is not given a large arbitrary expected-points bonus/penalty. Explicit modeled price paths affect legality; uncertain risk remains a bounded warning.

## Production safety
The established deterministic optimizer remains production authority. V3 multi-GW planning is still gated behind:

```json
"multigw": {
  "enabled": false,
  "shadow_mode": true
}
```

New Alpha 4 switches under the same block are:

```json
"include_chips": true,
"dominance_pruning": true,
"price_paths_enabled": true
```

## Tests
Dependency-free suite: **39 passed**.

New Alpha 4 regression coverage includes:

- Free Hit reverts to the permanent squad and preserves bank/FT mechanics.
- Wildcard permanently changes the squad and consumes only the Wildcard.
- The sequential planner can select Free Hit as a genuine best action.
- Safe state dominance removes an inferior state.
- A modeled £0.1m future rise can make a delayed transfer unaffordable.
- Optional price-risk metadata remains bounded and transparent.

Source and tests also pass Python compilation.

## Next milestone
Alpha 5 should add historical replay/snapshot infrastructure before promoting the V3 planner. That will let us compare V2 vs V3 transfer, captaincy and chip decisions without future-data leakage, and calibrate whether chip search/dominance/price features actually improve decisions.
