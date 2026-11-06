// node --test tests/js/*.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
globalThis.BN = require("../../site/metrics.js");
const BNC = require("../../site/commentary.js");

// ---- fixtures: deterministic random walks on business days ----
function rng(seed) { return () => ((seed = (seed * 16807) % 2147483647) / 2147483647); }
function bdays(n, end = "2026-11-04") {
  const out = []; let t = Date.parse(end + "T00:00:00Z");
  while (out.length < n) { const d = new Date(t); if (d.getUTCDay() % 6) out.unshift(d.toISOString().slice(0, 10)); t -= 864e5; }
  return out;
}
function walk(n, r, drift, vol = 0.01, start = 100) {
  const v = [start]; for (let i = 1; i < n; i++) v.push(+(v[i - 1] * (1 + drift + vol * (r() - 0.5) * 2)).toFixed(4)); return v;
}
function makeHist(pairs, n = 700, seed = 7) {
  const r = rng(seed), dates = bdays(n), adj = {}, close = {};
  pairs.forEach((p, k) => {
    adj[p.cap] = walk(n, r, 0.0006 + 0.0001 * k); adj[p.equal] = walk(n, r, 0.0003);
    close[p.cap] = adj[p.cap].slice(); close[p.equal] = adj[p.equal].slice();
  });
  return { dates, adj, close };
}
const SESSION = "2026-11-05", T0 = Date.UTC(2026, 10, 5, 14, 30) / 1000; // 09:30 ET
function quotesFor(hist, moves, minutes = 60) {
  const q = {};
  for (const [sym, path] of Object.entries(moves)) {
    const prev = hist.close[sym].at(-1);
    const t = path.map((_, i) => T0 + 60 * i * Math.floor(minutes / (path.length - 1 || 1)));
    const c = path.map((m) => +(prev * (1 + m)).toFixed(4));
    q[sym] = { price: c.at(-1), prevClose: prev, time: t.at(-1), session: SESSION, bars: { t, c } };
  }
  return q;
}
const SETTINGS = { rolling_window: 21, zscore_lookback: 252 };
const PAIRS = [
  { id: "a", name: "Alpha", cap: "AC", equal: "AE" },
  { id: "b", name: "Beta", cap: "BC", equal: "BE" },
  { id: "a_idx", name: "Alpha (index)", cap: "XC", equal: "XE", duplicate_of: "a" },
];

test("regime follows spread sign and index direction", () => {
  assert.equal(BNC.regime(0.01, 0.005).key, "narrow_rally");
  assert.equal(BNC.regime(-0.01, 0.005).key, "defensive");
  assert.equal(BNC.regime(0.01, -0.005).key, "broad_rally");
  assert.equal(BNC.regime(-0.01, -0.005).key, "unwind");
  assert.equal(BNC.regime(-0.01, -0.0005).key, "inline"); // under 10 bp
});

test("largestSince finds the last same-sign move at least as big", () => {
  const v = [NaN, -0.02, 0.03, -0.005, 0.001, -0.01];
  assert.deepEqual(BNC.largestSince(v, 5, -0.015), { j: 1, gap: 4 });
  assert.deepEqual(BNC.largestSince(v, 5, -0.05), { j: -1, gap: 5 });
});

test("ratioTrend classifies against 50/200-day averages", () => {
  const up = Array.from({ length: 260 }, (_, i) => 100 + i * 0.1);
  assert.equal(BNC.ratioTrend(up).key, "up");
  const pull = up.concat(Array.from({ length: 10 }, (_, i) => 125.9 - (i + 1) * 0.3));
  assert.equal(BNC.ratioTrend(pull).key, "up_pullback");
  const down = up.map((x) => 200 - x);
  assert.equal(BNC.ratioTrend(down).key, "down");
  assert.equal(BNC.ratioTrend(up.slice(0, 100)).key, "short");
});

test("compose: broadening day across indices, duplicate pair not double-counted", () => {
  const hist = makeHist(PAIRS);
  const quotes = quotesFor(hist, {
    AC: [0, -0.03, -0.02], AE: [0, -0.005, -0.005],  // Alpha: cap −2%, equal −0.5%: unwind
    BC: [0, 0.002, 0.004], BE: [0, 0.008, 0.012],     // Beta: cap +0.4%, equal +1.2%: broad rally
    XC: [0, 0.01, 0.01], XE: [0, -0.01, -0.01],       // duplicate disagrees; must be ignored
  });
  const r = BNC.compose({ hist, pairs: PAIRS, settings: SETTINGS, quotes, nowEpoch: T0 + 3600, marketOpen: true });
  assert.match(r.today[0], /^Equal-weight beat cap-weight in all 2 indices today/);
  assert.match(r.today[1], /^Alpha: AC −2\.00%, AE −0\.50%, the leaders sold hardest/);
  assert.match(r.today.join(" "), /narrowed from −250 bp at 10:00 ET to −150 bp: the move is fading/);
  assert.match(r.headline, /^The average stock beat the mega-caps across the board today \(Alpha −150 bp/);
  assert.equal(r.longer.length, 3);
  assert.match(r.longer[2], /^Return from holding AC rather than AE:/);
});

test("compose: figures match the overview table's snapshot", () => {
  const hist = makeHist(PAIRS, 700, 11);
  const quotes = quotesFor(hist, { AC: [0, 0.011], AE: [0, 0.004], BC: [0, 0.002], BE: [0, 0.001], XC: [0, 0], XE: [0, 0] });
  const r = BNC.compose({ hist, pairs: PAIRS, settings: SETTINGS, quotes, nowEpoch: T0 + 600, marketOpen: true });
  const snap = BN.snapshot(hist, PAIRS[0], quotes, 21, 252);
  const bp = Math.round(snap.today_spread * 1e4);
  assert.ok(r.headline.includes(`Alpha +${bp} bp`), r.headline);
  const m1 = (snap.spread_1M * 100).toFixed(1);
  assert.ok(r.longer[1].includes(`${m1.startsWith("-") ? "−" + m1.slice(1) : "+" + m1}pp`), r.longer[1]);
  assert.match(r.today[1], /a narrow rally led by the mega-caps/);
});

test("compose: stale thin leg is flagged only while the market is open", () => {
  const hist = makeHist(PAIRS);
  const quotes = quotesFor(hist, { AC: [0, 0.01], AE: [0, 0.005], BC: [0, 0.01], BE: [0, 0.01], XC: [0, 0], XE: [0, 0] }, 60);
  quotes.AE.time = T0 + 60; // AE last printed at 09:31
  const now = T0 + 3600;
  const open = BNC.compose({ hist, pairs: PAIRS, settings: SETTINGS, quotes, nowEpoch: now, marketOpen: true });
  assert.ok(open.notes.some((n) => n.startsWith("AE last traded 59 min ago")), open.notes.join("|"));
  const shut = BNC.compose({ hist, pairs: PAIRS, settings: SETTINGS, quotes, nowEpoch: now, marketOpen: false });
  assert.equal(shut.notes.length, 0);
});

test("compose: previous session is dated, not called today", () => {
  const hist = makeHist(PAIRS);
  const quotes = quotesFor(hist, { AC: [0, 0.01], AE: [0, 0.02], BC: [0, 0.01], BE: [0, 0.02], XC: [0, 0], XE: [0, 0] });
  const nextMorning = Date.UTC(2026, 10, 6, 10, 0) / 1000;
  const r = BNC.compose({ hist, pairs: PAIRS, settings: SETTINGS, quotes, nowEpoch: nextMorning, marketOpen: false });
  assert.match(r.today[0], /on 5 Nov 2026/);
  assert.doesNotMatch(r.headline, /today/);
});

test("compose: no intraday bars still produces the longer-term lane", () => {
  const hist = makeHist(PAIRS);
  const r = BNC.compose({ hist, pairs: PAIRS, settings: SETTINGS, quotes: {}, nowEpoch: T0, marketOpen: false });
  assert.deepEqual(r.today, ["No intraday bars yet."]);
  assert.match(r.longer[0], /^Alpha cap\/equal ratio is /);
  assert.match(r.headline, /^Concentration (is|remains)/);
});
