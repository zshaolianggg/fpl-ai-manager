# FPL AI Manager V3 Alpha 4 post1 — GW1 structural fix

This hotfix addresses a design gap exposed by a real Alpha 3 GW1 recommendation where an expensive £7.5m forward was placed deep on the bench while cheaper midfielders started.

## What changed

- GW1 ILP is now a **candidate generator only**. It no longer determines the final ranking.
- GW1 candidates are reranked using the V3 probabilistic lineup model:
  - expected automatic substitutions,
  - captain/vice fallback value,
  - fixture-level appearance probabilities,
  - multi-GW probabilistic lineup utility.
- Added **dormant-capital / deep-bench diagnostics**. Expensive outfield assets parked in deep bench slots receive a small bounded structural penalty unless they are projected to become regular starters over the next five GWs.
- Added **role-aware minutes priors**. Established high-minute players receive stronger generic start priors when current-season evidence is sparse; premium/high-owned attacking anchors receive only a bounded additional prior. There are no player-name rules.
- Reports now identify the production decision engine explicitly and distinguish production from shadow models.
- Removed stale GW1 wording implying that the final V3 squad is selected with a fixed 20% bench weight.
- Evidence payload now describes GW1 bench valuation as **probabilistic auto-sub-aware**.

## Safety / compatibility

- Legal squad generation remains ILP-backed and unchanged in its FPL constraints.
- Structural penalties are bounded tie-breakers; they cannot overwhelm large football projection advantages.
- An expensive GW1 bench player can still be selected when the model explicitly projects enough near-term starting usage to justify the capital.
- Managed-squad V2 optimizer remains production authority outside GW1; V3 multi-GW remains shadow.

## Tests

- 44 tests passed.
- New tests cover:
  - premium role-aware start priors,
  - unknown-player priors remaining conservative,
  - expensive deep-bench detection,
  - structural penalty behavior,
  - explicit production-engine reporting,
  - prevention of stale `20%-weighted bench` report text on the V3 GW1 path.
