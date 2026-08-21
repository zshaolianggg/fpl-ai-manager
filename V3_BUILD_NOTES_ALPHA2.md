# FPL AI Manager V3 Alpha 2

Version: `3.0.0a2`

## Scope

This milestone adds the first sequential-decision layer on top of the V3 projection engine while preserving the existing V2 optimizer as the production fallback.

### Probabilistic lineup and auto-subs

`lineup.py` now exposes fixture/GW appearance probabilities and estimates automatic-substitution value from starter no-show risk and ordered bench availability. The best bench order is searched across the three outfield substitutes. Captain fallback to the vice-captain is included in the probabilistic score, including Triple Captain multiplier behavior.

The legacy `score` and `robust_score` fields remain unchanged for existing consumers. New fields are additive: `probabilistic_score`, `expected_auto_sub_points`, and `captain_fallback_points`.

### ManagerState and transfer transitions

New `multigw.py` introduces an immutable `ManagerState` containing gameweek, squad, bank, free transfers, and verified selling-price ledger. State transitions explicitly apply transfer costs, hits, bank changes, squad legality, and FT accumulation up to five.

New purchases enter the shadow ledger at current price. Live future price changes are intentionally deferred to the V3.3 price layer.

### Multi-GW beam search

`plan_multigw()` searches a sequence of future transfer decisions rather than evaluating one permanently changed squad across a horizon. `ROLL` is always an action and receives no arbitrary bonus: its value emerges only if the extra FT improves a later path.

The candidate pool unions raw projection leaders, value leaders, and price-tier players so structural enablers survive pruning.

### Shadow integration

`main.py` can run the new planner in shadow mode via `config/manager.json -> multigw.enabled`. Shadow output is added to the AI/evidence payload but does not replace the established optimizer decision path. Any shadow-planner exception becomes a warning rather than blocking a recommendation.

The switch remains `false` in this package until full-environment runtime profiling is completed.

## Regression coverage

28 dependency-free tests pass, including all prior state, lineup, captaincy, market-prior, uncertainty, chip-policy and V3 projection tests plus new tests for:

- probabilistic auto-sub value increasing with starter no-show risk;
- captain-to-vice fallback value;
- rolling from one FT to two;
- -4 hit arithmetic for two transfers with one FT;
- a sequential scenario where the optimal first action is ROLL, followed by two free transfers next GW.

`python -m compileall` also succeeds.

PuLP remains required for the existing ILP squad builder, but it is now imported optionally so non-ILP modules and tests work in lightweight environments. Calling an ILP function without PuLP raises a clear runtime error.

## Next milestone

Recommended Alpha 3 scope:

1. dedicated captaincy distribution module (`p_blank`, `p_10+`, `p_15+`, downside/upside utility);
2. multi-GW runtime profiling and caching against a live-size player pool;
3. promote multi-GW output from shadow evidence to deterministic near-tie comparison only after profiling;
4. chip opportunity-cost engine using future path value;
5. persistent Elite registry and transfer-in/out movement signals.
