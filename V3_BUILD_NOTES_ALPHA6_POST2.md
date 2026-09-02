# V3 Alpha 6 post2

Version: `3.0.0a6.post2`

## Fixes

### 1. Equal-horizon V2/V3 common-basis comparison

The previous common-basis evaluator could compare a complete V2 continuation with a V3 shadow path that had been truncated by its runtime budget. In the observed GW3 run this produced the impossible-looking comparison of roughly 165 vs 111 points while both first-GW scores were around 55.

Post2 no longer reuses the possibly truncated V3 shadow total for the common comparison. Instead it:

1. takes the V2 production first action;
2. takes the V3 shadow first action;
3. replays each first action independently inside the same V3 probabilistic state model;
4. optimises the continuation for the exact same remaining gameweeks with the same settings; and
5. publishes a common-basis result only if both routes contain exactly the requested GW list.

If either route times out or returns fewer gameweeks, the common-basis result is marked unavailable instead of comparing unequal horizons.

The report now includes the explicit evaluated GW list and per-GW net scores, e.g. `GW3: V2 x / V3 y; GW4: ...`, making future horizon mismatches directly visible.

### 2. Email sections expanded / no repeated-message collapse

The HTML renderer is deliberately flat: no `<details>`, `<summary>`, accordion, hidden section, or collapsed block is generated.

Repeated Preview runs previously used the exact same subject. Mail clients can group those messages into one conversation and collapse repeated content behind an expand/show-trimmed-content control. Post2 therefore sends each run with:

- a timestamped unique subject by default;
- a unique `Message-ID`;
- a unique `X-FPL-Run-ID`;
- a visible generated-at timestamp in the HTML body.

Set `EMAIL_UNIQUE_SUBJECTS=false` only if conversation threading is explicitly preferred.

Note: a mail client can always apply its own UI collapsing rules; the project itself now emits no collapsible sections and avoids the repeated-subject threading pattern that triggered the observed behaviour.

### 3. AI explanation safety

The optional explainer receives common-basis data only when its status is `available`, including the explicit GW list and per-GW scores. If no fair equal-horizon comparison is available, it is instructed to state that rather than infer superiority from native V2/V3 scores.

## Validation

- `69 passed`
- source/tests/scripts compile successfully
- regression coverage added for flat email HTML, unique per-run subjects, explicit GW lists in the explanation packet, and equal 3-GW common-basis horizons.
