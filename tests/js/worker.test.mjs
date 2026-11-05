// node --test tests/js/*.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { parseChart, buildLive, nyDate } from "../../worker/src/live.js";
import { slotFor, scheduledDate, allowedSymbols, serveLive } from "../../worker/src/index.js";

// Shape of Yahoo's v8 chart response (fields used by parseChart only).
const chart = (sym, t0, closes, extra = {}) => ({
  meta: { symbol: sym, regularMarketPrice: closes.filter((c) => c != null).at(-1),
          regularMarketTime: t0 + 60 * (closes.length - 1), chartPreviousClose: 100, ...extra },
  timestamp: closes.map((_, i) => t0 + 60 * i),
  indicators: { quote: [{ close: closes }] },
});
const T0 = Date.UTC(2026, 10, 5, 14, 30) / 1000; // 09:30 New York, 5 Nov 2026

test("parseChart drops null bars and dates the session in New York", () => {
  const q = parseChart(chart("QQQE", T0, [101, null, 102.123456]));
  assert.deepEqual(q.bars.t, [T0, T0 + 120]);
  assert.deepEqual(q.bars.c, [101, 102.1235]);
  assert.equal(q.session, "2026-11-05");
  assert.equal(q.prevClose, 100);
});

test("late-evening UTC bars still belong to the New York date", () => {
  assert.equal(nyDate(Date.UTC(2026, 10, 6, 2, 0) / 1000), "2026-11-05");
});

test("buildLive reports per-symbol failures without failing the rest", async () => {
  const fake = async (url) => url.includes("BAD")
    ? new Response("<html>blocked</html>", { status: 403 })
    : new Response(JSON.stringify({ chart: { result: [chart("QQQM", T0, [1, 2])] } }));
  const p = await buildLive(["QQQM", "BAD"], "test", fake);
  assert.deepEqual(Object.keys(p.quotes), ["QQQM"]);
  assert.equal(p.errors.length, 1);
  assert.match(p.errors[0].detail, /query1: 403.*query2: 403/);
});

test("serveLive only requests allow-listed symbols and sets CORS", async () => {
  const seen = [];
  const fake = async (url) => { seen.push(decodeURIComponent(url.split("/chart/")[1].split("?")[0]));
    return new Response(JSON.stringify({ chart: { result: [chart("X", T0, [1, 2])] } })); };
  const r = await serveLive({ SYMBOLS: "QQQM, QQQE" }, fake);
  assert.equal(r.headers.get("Access-Control-Allow-Origin"), "*");
  assert.deepEqual(seen.sort(), ["QQQE", "QQQM"]);
  assert.deepEqual(allowedSymbols({ SYMBOLS: "A,,B " }), ["A", "B"]);
});

test("schedule is anchored to New York across EST and EDT", () => {
  // 13:35 UTC = 09:35 EDT (Oct) ; 14:35 UTC = 09:35 EST (Nov, after the clocks change)
  assert.ok(slotFor(new Date(Date.UTC(2026, 9, 15, 13, 35))));
  assert.equal(slotFor(new Date(Date.UTC(2026, 10, 12, 13, 35))), null);
  assert.ok(slotFor(new Date(Date.UTC(2026, 10, 12, 14, 35))));
  assert.equal(slotFor(new Date(Date.UTC(2026, 10, 14, 14, 35))), null); // Saturday
  assert.equal(scheduledDate({ scheduledTime: 1e9 }).getUTCFullYear(), 2001); // seconds
});
