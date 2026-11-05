/**
 * BreadthNavigator Worker.
 *
 *   GET /live   live 1-minute bars for the allow-listed symbols (env.SYMBOLS), open CORS.
 *   POST /      manual rebuild (X-Trigger-Key), dispatches the Pages workflow.
 *   cron        dispatches the Pages workflow at New York-anchored windows, so daily
 *               history on the page is refreshed before the open and after the close.
 *
 * GitHub's own `schedule:` is best-effort (see BondDashboard: delays of 8+ hours and
 * dropped firings in Aug 2026), so the schedule lives here and the workflow's cron is
 * only a backstop. Cloudflare cron is UTC-only; the gate below anchors to New York so
 * EST/EDT need no handling.
 */
import { buildLive } from "./live.js";

/** New York hours (at :35) the page rebuilds on. */
export const SLOTS = {
  9: "before the open: yesterday's final adjusted closes",
  12: "midday redundancy",
  16: "after the close: the session's daily bar",
  18: "evening redundancy, after Yahoo settles the day",
};

export function scheduledDate(event) {
  const t = Number(event?.scheduledTime);
  if (!Number.isFinite(t) || t <= 0) return new Date();
  return new Date(t < 1e11 ? t * 1000 : t); // seconds vs milliseconds
}

export function nyParts(date) {
  const got = {};
  for (const p of new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", weekday: "short", hour: "2-digit", hour12: false,
  }).formatToParts(date)) got[p.type] = p.value;
  return { weekday: got.weekday, hour: parseInt(got.hour, 10) % 24 };
}

export function slotFor(date) {
  const { weekday, hour } = nyParts(date);
  if (weekday === "Sat" || weekday === "Sun") return null;
  return SLOTS[hour] || null;
}

export function allowedSymbols(env) {
  return String(env.SYMBOLS || "").split(",").map((s) => s.trim()).filter(Boolean);
}

export async function dispatchWorkflow(env, reason) {
  const url = `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}` +
    `/actions/workflows/${env.WORKFLOW_FILE}/dispatches`;
  if (!env.GITHUB_TOKEN) return { ok: false, status: 0, detail: "GITHUB_TOKEN secret is not set" };
  const resp = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": `${env.GITHUB_REPO}-refresh-worker`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: env.GIT_REF || "main" }),
  });
  if (resp.status === 204) {
    console.log(`dispatched ${env.WORKFLOW_FILE} (${reason})`);
    return { ok: true, status: 204, detail: "dispatched" };
  }
  const detail = (await resp.text()).slice(0, 500);
  console.log(`dispatch failed ${resp.status} (${reason}): ${detail}`);
  return { ok: false, status: resp.status, detail };
}

/**
 * Held LIVE_TTL seconds per isolate and cached at the edge for the same, so however
 * many tabs poll, Yahoo sees a handful of requests a minute. Only the fixed symbol
 * list is ever requested, so this is not an open proxy.
 */
export const LIVE_TTL = 30;
let memo = null;

export async function serveLive(env, fetchImpl = fetch) {
  const now = Date.now();
  if (!memo || now - memo.at > LIVE_TTL * 1000) {
    const payload = await buildLive(allowedSymbols(env), "worker", fetchImpl, {
      cf: { cacheTtl: LIVE_TTL, cacheEverything: true },
    });
    if (payload.errors.length) {
      console.log(`live: ${payload.errors.length} symbol(s) failed: ` +
        payload.errors.map((e) => `${e.symbol} ${e.detail}`).join(" | ").slice(0, 800));
    }
    memo = { at: now, body: JSON.stringify(payload) };
  }
  return new Response(memo.body, {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": `public, max-age=${LIVE_TTL}`,
      "Access-Control-Allow-Origin": "*",
    },
  });
}

export default {
  async scheduled(event, env, ctx) {
    const when = scheduledDate(event);
    const { weekday, hour } = nyParts(when);
    const slot = slotFor(when);
    if (!slot) { console.log(`skipped: ${weekday} ${hour}:35 New York is not a build window`); return; }
    console.log(`firing: ${weekday} ${hour}:35 New York - ${slot}`);
    ctx.waitUntil(dispatchWorkflow(env, `cron ${hour}:35 New York`));
  },

  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: { "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET" } });
    }
    if (request.method === "GET" && new URL(request.url).pathname === "/live") return serveLive(env);
    if (request.method !== "POST") {
      return new Response("GET /live for live bars; POST with X-Trigger-Key to rebuild\n", { status: 405 });
    }
    if (!env.TRIGGER_KEY || request.headers.get("X-Trigger-Key") !== env.TRIGGER_KEY) {
      return new Response("unauthorised\n", { status: 401 });
    }
    const result = await dispatchWorkflow(env, "manual");
    return new Response(JSON.stringify(result, null, 2) + "\n", {
      status: result.ok ? 202 : 502, headers: { "Content-Type": "application/json" },
    });
  },
};
