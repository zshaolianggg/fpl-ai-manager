# Reliable external scheduler

GitHub scheduled workflows are best-effort and can be delayed or dropped. This
Cloudflare Worker provides the primary hourly clock and invokes the existing
GitHub `workflow_dispatch` endpoint. The native GitHub cron remains enabled as
a backup; the manager's report-state logic prevents duplicate emails.

## One-time setup

1. Create a Cloudflare Worker and copy `worker.js` plus a `wrangler.toml` based
   on `wrangler.toml.example`.
2. Create a fine-grained GitHub personal access token scoped to this repository
   with **Actions: Read and write** permission. Do not commit it.
3. Store it as a Worker secret:

   ```bash
   npx wrangler secret put GITHUB_TOKEN
   ```

4. Set `GITHUB_OWNER` and `GITHUB_REPO` in `wrangler.toml` or the Cloudflare
   dashboard.
5. Deploy:

   ```bash
   npx wrangler deploy
   ```

The example cron is `17 * * * *` (UTC): one external dispatch every hour.
Cloudflare cron expressions use UTC. The workflow itself computes the FPL
window from the configured timezone and official deadline, so the scheduler
needs no FPL-specific timezone logic.

## Verify

In GitHub Actions, externally triggered runs should show event
`workflow_dispatch`, and the **Scheduler diagnostics** step should show:

```text
trigger_source=cloudflare-cron
```

Native GitHub backup runs show `event_name=schedule`.
