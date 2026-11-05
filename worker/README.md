# BreadthNavigator Worker

Two jobs, same pattern as BondDashboard's Worker:

1. **`GET /live`**: live 1-minute bars (Yahoo chart endpoint, keyless) for the symbols in
   `SYMBOLS` (`wrangler.toml`). The Pages site polls it every 60s while the tab is visible
   and the US market is open, and recomputes every spread in the browser. Open CORS, no key;
   only the allow-listed symbols are ever fetched, so it is not an open proxy. The payload is
   held for 30s, so any number of open tabs costs Yahoo a few requests a minute. 12 symbols ×
   up to 2 Yahoo hosts = 24 subrequests, inside the free plan's 50.
2. **Cron → `workflow_dispatch`**: rebuilds the Pages site (daily history) at 09:35, 12:35,
   16:35 and 18:35 **New York** time on weekdays. GitHub's own cron is best-effort; the
   workflow keeps three `schedule:` slots only as a backstop.

## Deploy (once)

Cloudflare free plan, no domain needed.

**Route A, connect the repo (Workers Builds):** create a Worker from this Git repository,
then under Settings → Build set **Root directory = `worker`**, build command empty,
deploy command `npx wrangler deploy`. Keep `name` in `wrangler.toml` (`breadthnavigator`)
equal to the Worker's name in Cloudflare.

**Route B, from a laptop:**

```bash
cd worker && npx wrangler login && npx wrangler deploy
```

Then the secrets (dashboard: Settings → Variables and Secrets, or):

```bash
npx wrangler secret put GITHUB_TOKEN   # fine-grained PAT: only this repo, Actions: Read and write
npx wrangler secret put TRIGGER_KEY    # optional, any long random string, for manual rebuilds
```

Finally point the page at the feed: GitHub repo → Settings → Secrets and variables →
Actions → **Variables** → `LIVE_URL` = `https://breadthnavigator.<your-subdomain>.workers.dev/live`.
The next build bakes it in.

## Verify

```bash
curl https://breadthnavigator.<your-subdomain>.workers.dev/live | head -c 400
```

```bash
curl -X POST https://breadthnavigator.<your-subdomain>.workers.dev/ -H "X-Trigger-Key: <TRIGGER_KEY>"
```

Expect quotes (and an empty `errors` list) from the first; `202 {"ok": true, ...}` and a new
Actions run from the second. `npx wrangler tail` shows `firing:` / `skipped:` per cron tick
(13 a day, 4 of which build) and `live: N symbol(s) failed` if Yahoo refuses.

## Adding a symbol

Add the pair to `config/pairs.yaml` **and** the symbols to `SYMBOLS` here (both `[vars]` and
`[previews.vars]`). `tests/test_site.py` fails the build if you forget the second.
