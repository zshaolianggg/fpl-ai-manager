# V3 Alpha 6 post3 build notes

Version: `3.0.0a6.post3`

## Captaincy calibration
- The probabilistic captaincy utility now keeps expected points dominant but adds small bounded rewards for P(10+), attacking-return probability, and xG+xA rate.
- Captain/vice pair ranking now uses that calibrated utility; expected extra captain points remain separately reported.
- The production captain policy is now audited with an explicit reason, including when the low-confidence premium-anchor rule overrides the raw top projected captain.

## Beginner-friendly reporting
- Added a prominent **What to do** section with transfers, hit, bank, captain/vice and chip action.
- Renamed technical wording: common-basis -> same-gameweeks comparison; equivalence band -> close-call rule; V2/V3 descriptions are framed as weekly model vs future-planning check.
- Transfer-signal labels now explain what STRONG/MODERATE/WEAK mean.
- Expected gain and confidence headings use plain language.
- Optional AI explanation is instructed to write for a casual/beginner player and avoid database/model field names.

## Safety
- Production decision remains deterministic.
- AI remains explanation-only.
- Wildcard/Free Hit remain shadow-only.
