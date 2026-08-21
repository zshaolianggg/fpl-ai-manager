# FPL AI Manager V3 Alpha 3 Build Notes

Version: `3.0.0a3`

Alpha 3 extends Alpha 2 in three areas: multi-GW search performance, probabilistic captaincy, and chip opportunity cost.

## 1. Multi-GW planner memoization

`multigw.py` now has a per-run `PlannerCache` for lineup evaluations, candidate actions, and transitions. The planner reports cache diagnostics in each returned path. Caching can be disabled with `multigw.cache_enabled` for A/B validation.

On the deterministic two-GW regression workload in this build environment, five-run average search time was approximately:

- uncached: 0.59 seconds
- cached: 0.18 seconds
- speedup: about 3.2x

This is a micro-benchmark, not a claim about full live FPL runtime. Live-size candidate pools still need profiling before the multi-GW planner leaves shadow mode.

## 2. Dedicated probabilistic captaincy engine

New module: `src/fpl_ai_manager/captaincy.py`.

For every starter it exposes:

- expected points
- variance / standard deviation
- P10 and P90 envelope
- P(10+)
- P(appearance)
- P(zero minutes)
- bounded risk-adjusted utility

Captain and vice-captain are selected jointly. The value of a vice-captain is explicitly conditional on the captain recording zero minutes. Defender/GK captaincy is still allowed when the projection edge is genuinely large, but a close raw edge does not automatically displace a strong attacking captain.

The V2 production captaincy remains authoritative. Alpha 3 adds `captaincy_shadow` to the evidence/AI payload and the multi-GW probabilistic lineup path uses the new engine.

## 3. Chip opportunity cost

Bench Boost and Triple Captain no longer depend on fixed activation thresholds in the Alpha 3 chip path.

For the current squad, the engine calculates each chip's incremental value in every projected GW remaining in the half-season window that is currently available in projections. It then compares:

`current incremental value - reserve_factor * best future modeled value`

A chip is offered only when the resulting net opportunity edge clears `minimum_opportunity_edge_points`.

Triple Captain uses the new probabilistic captain/vice pair, so its incremental value includes vice takeover when the captain records zero minutes.

Free Hit and Wildcard remain hybrid models for now. Their existing modeled-gain hurdles receive an additional reserve when confirmed future blank/double structure exists. Full opportunity-cost treatment requires simulating those chips inside the future-state optimizer and is intentionally deferred.

## Configuration additions

`captaincy`:

- `probabilistic_shadow`
- `downside_penalty`
- `upside_bonus`
- `probabilistic_defender_override_margin`

`multigw`:

- `cache_enabled`
- `include_diagnostics`

`chips`:

- `opportunity_cost_enabled`
- `future_opportunity_reserve_factor`
- `minimum_opportunity_edge_points`
- `confirmed_structure_reserve_points`
- `max_structure_reserve_points`

## Validation

Dependency-free test suite: **33 passed**.

New Alpha 3 regression coverage includes:

- repeated multi-GW states reuse lineup calculations
- captain/vice pair value increases with a stronger vice when captain no-show risk exists
- probabilistic captaincy emits distribution data
- a marginal defender projection does not bypass the attacking captain guardrail
- Triple Captain waits when a materially better future projected window is visible
- Triple Captain can be used when the current opportunity dominates the visible future window

All package Python modules compile successfully.

## Promotion status

- V2 deterministic optimizer: production authority
- V3 multi-GW planner: shadow mode
- V3 probabilistic captaincy: shadow mode for the production decision payload; active inside probabilistic multi-GW lineup scoring
- V3 BB/TC opportunity-cost chip model: implemented in the chip-plan generator
- V3 FH/WC: hybrid opportunity reserve, not yet full future-state simulation

## Recommended Alpha 4 milestone

1. Put Free Hit and Wildcard directly into `ManagerState` / multi-GW transitions so their opportunity cost is endogenous.
2. Add state-dominance pruning to the beam search (same squad with inferior bank/FT state can be discarded safely under defined conditions).
3. Add price-path and affordability risk so future plans know when a 0.1m move can close a route.
4. Start a replay/backtest harness to compare V2 vs V3 shadow recommendations without future-data leakage.
