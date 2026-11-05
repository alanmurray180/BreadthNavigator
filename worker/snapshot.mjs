#!/usr/bin/env node
/**
 * Build-time snapshot of the live feed: writes live.json for build_static.py to bake in.
 * Runs the same live.js as the Worker. Never fails the build - the daily history is
 * the backbone of the page; failures go into the payload and a run annotation.
 *
 *   node worker/snapshot.mjs out.json SYM1,SYM2,...
 */
import { writeFileSync } from "node:fs";
import { buildLive } from "./src/live.js";

const out = process.argv[2] || "live.json";
const symbols = (process.argv[3] || "").split(",").filter(Boolean);
let payload;
try {
  payload = await buildLive(symbols, "build");
} catch (e) {
  payload = { generated: new Date().toISOString(), source: "build", quotes: {},
    errors: [{ symbol: "*", detail: String(e?.message || e) }] };
}
writeFileSync(out, JSON.stringify(payload));
console.error(`live snapshot: ${Object.keys(payload.quotes).length} symbols, ` +
  `${payload.errors.length} error(s) -> ${out}`);
if (payload.errors.length && process.env.GITHUB_ACTIONS) {
  const d = payload.errors.map((e) => `${e.symbol}: ${e.detail}`).join(" · ").slice(0, 900);
  console.log(`::warning title=Live quotes unavailable at build::${d}`);
}
