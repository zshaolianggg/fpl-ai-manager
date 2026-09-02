# FPL AI Manager V3 Alpha 6 post1

Version: `3.0.0a6.post1`

This is a focused correctness/reporting patch on top of Alpha 6. The production decision architecture remains deterministic; AI remains explanation-only.

## Fixes

### Captaincy shadow audit now matches the engine objective
The probabilistic captaincy engine optimizes the captain/vice pair, not individual captain utility alone. The report now ranks alternative captain choices by pair value, shows the selected pair value, and separately reports the production captain's individual utility and pair rank. This removes misleading cases where the displayed next captain candidate had a higher individual utility than the selected shadow captain without explaining the vice-captain interaction.

### Money is normalized before AI explanation
FPL internal prices are stored in tenths. The explanation packet now converts bank, buy and sell prices to human-readable values such as `£2.5m` before the optional AI call. Raw values such as `25` can no longer be rendered as `£25`.

### Native V2 and V3 scores are explicitly non-comparable
`optimizer_score` from V2 and the sequential `path score` from V3 use different objectives and horizons. They are now marked as non-comparable, removed from the AI explanation packet as a basis for cross-engine claims, and accompanied by an explicit warning in audit metadata.

### Common-basis V2 vs V3 route comparison
When runtime permits, the selected V2 first action is replayed inside the V3 probabilistic state model. V2 then receives the same bounded sequential continuation search as V3. Both routes are scored over the same short horizon, with the same discount and net-of-hit objective. The report shows:

- V2 common-basis score
- V3 common-basis score
- V3 minus V2 delta
- first-GW score on the common objective
- bank after the first action

The common-basis comparison has an 8-second continuation budget and is skipped/fails soft if unavailable.

## Validation

- `PYTHONPATH=src pytest -q`: **66 passed**
- `python -m compileall -q src tests scripts`: passed

New regression tests cover human-readable money in the explanation packet and prevention of native V2/V3 score comparison.
