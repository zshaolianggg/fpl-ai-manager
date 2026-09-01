/**
 * Cloudflare Cron -> GitHub Actions workflow_dispatch heartbeat.
 *
 * Required Worker secret:
 *   GITHUB_TOKEN  fine-grained GitHub token with Actions: Read and write
 *
 * Required vars (wrangler.toml or Cloudflare dashboard):
 *   GITHUB_OWNER
 *   GITHUB_REPO
 * Optional:
 *   GITHUB_REF       defaults to main
 *   GITHUB_WORKFLOW  defaults to fpl-manager.yml
 */
export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(dispatch(env));
  },

  async fetch(request, env) {
    // Optional health endpoint. It never dispatches a workflow.
    return new Response("FPL scheduler alive\n", { status: 200 });
  },
};

async function dispatch(env) {
  const owner = env.GITHUB_OWNER;
  const repo = env.GITHUB_REPO;
  const workflow = env.GITHUB_WORKFLOW || "fpl-manager.yml";
  const ref = env.GITHUB_REF || "main";
  if (!owner || !repo || !env.GITHUB_TOKEN) {
    throw new Error("Missing GITHUB_OWNER, GITHUB_REPO, or GITHUB_TOKEN");
  }

  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflow}/dispatches`;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "fpl-ai-manager-external-scheduler",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ref,
      inputs: {
        force_report: "",
        trigger_source: "cloudflare-cron",
      },
    }),
  });

  if (response.status !== 204) {
    const body = await response.text();
    throw new Error(`GitHub dispatch failed (${response.status}): ${body}`);
  }
  console.log(`Dispatched ${workflow} on ${ref} at ${new Date().toISOString()}`);
}
