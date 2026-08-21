# FPL AI Manager V3 Alpha - Projection Milestone

## Implemented

- Season-aware scoring rules in `rules.py`.
- 2026/27 goalkeeper goal scoring corrected to 10 points.
- 2026/27 defensive-contribution thresholds represented explicitly.
- Dynamic team-strength model from official FPL team attack/defence ratings.
- Removed FDR-to-attack and FDR-to-clean-sheet hard-coded lookup tables from the primary projection path.
- Fixture-level `MinutesProjection` with start, appearance, 60+, zero-minute probabilities and reasons.
- Fixture congestion changes start probability instead of applying one blanket future-minutes multiplier.
- `FixtureProjection` component breakdown and uncertainty envelope.
- Defensive-contribution expectation from recent CBIT/CBIRT action rates with threshold probability.
- Explicit set-piece role adapter/scaffolding.
- Season is now configuration-driven (`season: 2026/27`); Understat year is derived from it.
- Existing V2 optimizer compatibility fields retained (`expected_minutes`, `confidence`, `gw1`, `gw3`, `gw6`, `gw8`).
- OpenAI import in `news.py` made lazy so projection/unit modules can be imported without the SDK present.

## Validation completed

- Python source and tests compile cleanly.
- 16 dependency-free tests pass, including legacy core/lineup/captain guardrails and 5 new V3 tests.

## Environment limitation

The full legacy test suite could not be run in the build container because `pulp` and `openai` are not installed and the container has no package-download network. This is an environment limitation, not a failing assertion. Run `pip install -r requirements.txt` and `python -m unittest discover -s tests -v` in the normal project environment before deployment.

## Next milestone

1. Probabilistic auto-sub / bench-order valuation.
2. Dedicated captaincy distribution module.
3. Formal manager-state transitions for bank/free transfers/selling prices.
4. Multi-GW beam-search optimizer with explicit value for rolling transfers.
5. Chip opportunity-cost layer.
