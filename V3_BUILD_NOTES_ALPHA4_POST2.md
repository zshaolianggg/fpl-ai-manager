# V3 Alpha 4 post2

## Reliability patch

### Public selling-price reconstruction

Public `/entry/{id}/event/{gw}/picks/` responses contain picks and entry
history, but normally do not expose private `purchase_price` / `selling_price`
fields. The previous implementation therefore withheld managed-squad reports
when those fields were absent.

The manager now reconstructs purchase basis from public FPL data:

1. latest permanent transfer-in `element_in_cost`, when the player was bought
   after GW1;
2. otherwise the season-start price, reconstructed as
   `now_cost - cost_change_start` for a player held since GW1;
3. Free Hit transfer events are ignored because they do not reset the permanent
   squad's purchase-price ledger.

The official half-profit selling-price rule is then applied to that reconstructed
purchase basis. The source of each reconstructed basis is retained as
`price_basis` and surfaced as a non-blocking warning for auditability.

### Scheduler resilience

The GitHub workflow keeps native hourly `schedule` as a backup and now supports
an explicit external `workflow_dispatch` heartbeat. A ready-to-deploy
Cloudflare Cron Worker is included under `scheduler/cloudflare/`.

The workflow also logs trigger source, actual UTC start time, preflight result,
report type, GW, and delivery mode. A concurrency group prevents overlapping
manager jobs from racing when native and external triggers arrive together.
