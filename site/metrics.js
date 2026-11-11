/**
 * BreadthNavigator page calculations - the JavaScript twin of breadthnav/metrics.py.
 *
 * The page appends the live price to the build's daily history and recomputes in the
 * browser, so these must agree with the Python. tests/test_js_parity.py runs both on
 * the same prices and fails if they drift.
 *
 * Plain script (no import/export) so build_static.py can inline it; exported for Node
 * through module.exports for the tests.
 */
const BN = (() => {
  const PERIODS = ["1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "3Y", "Since start"];
  const MONTHS = { "1M": 1, "3M": 3, "6M": 6, "1Y": 12, "3Y": 36 };

  // ---- dates as 'YYYY-MM-DD' strings (compare lexically) ----
  const pad = (n) => String(n).padStart(2, "0");
  const ymd = (y, m, d) => `${y}-${pad(m)}-${pad(d)}`;
  const parts = (s) => s.split("-").map(Number);

  /** pandas DateOffset(months=n) backwards: clip the day to the target month's end. */
  function subMonths(s, n) {
    let [y, m, d] = parts(s);
    m -= n;
    while (m < 1) { m += 12; y -= 1; }
    const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
    return ymd(y, m, Math.min(d, last));
  }
  function subDays(s, n) {
    const [y, m, d] = parts(s);
    const t = new Date(Date.UTC(y, m - 1, d - n));
    return ymd(t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate());
  }

  /** {dates, cap, equal} on the dates both legs have a price. */
  function pairPrices(hist, pair, field = "adj") {
    const a = hist[field][pair.cap], b = hist[field][pair.equal];
    const out = { dates: [], cap: [], equal: [] };
    if (!a || !b) return out;
    hist.dates.forEach((d, i) => {
      if (a[i] != null && b[i] != null) { out.dates.push(d); out.cap.push(a[i]); out.equal.push(b[i]); }
    });
    return out;
  }

  /** Last index whose date satisfies pred, or -1. Dates ascending. */
  function lastWhere(dates, pred) {
    for (let i = dates.length - 1; i >= 0; i--) if (pred(dates[i])) return i;
    return -1;
  }

  function baseIndex(p, period) {
    const n = p.dates.length, end = p.dates[n - 1];
    if (period === "1D") return n > 1 ? n - 2 : -1;
    if (period === "Since start") return 0;
    if (period === "YTD") { const jan1 = `${end.slice(0, 4)}-01-01`; return lastWhere(p.dates, (d) => d < jan1); }
    const cut = period === "1W" ? subDays(end, 7) : subMonths(end, MONTHS[period]);
    return lastWhere(p.dates, (d) => d <= cut);
  }

  /** {period: {cap, equal, spread}} - decimals, NaN where history is too short. */
  function periodReturns(p) {
    const n = p.dates.length, out = {};
    for (const per of PERIODS) {
      const i = n ? baseIndex(p, per) : -1;
      if (i < 0) { out[per] = { cap: NaN, equal: NaN, spread: NaN }; continue; }
      const c = p.cap[n - 1] / p.cap[i] - 1, e = p.equal[n - 1] / p.equal[i] - 1;
      out[per] = { cap: c, equal: e, spread: c - e };
    }
    return out;
  }

  /** Index of the first date >= start (0 when start is null). */
  function startIndex(p, start) {
    if (!start) return 0;
    const i = p.dates.findIndex((d) => d >= start);
    return i < 0 ? p.dates.length - 1 : i;
  }

  function rebased(p, start = null) {
    const i0 = startIndex(p, start);
    return {
      dates: p.dates.slice(i0),
      cap: p.cap.slice(i0).map((v) => v / p.cap[i0] * 100),
      equal: p.equal.slice(i0).map((v) => v / p.equal[i0] * 100),
    };
  }

  /** Cap/equal total-return ratio rebased to 100. Rising = cap-weighted outperforming. */
  function relativeRatio(p, start = null) {
    const r = rebased(p, start);
    return { dates: r.dates, values: r.cap.map((c, i) => c / r.equal[i] * 100) };
  }

  /** Trailing `w`-session return of cap minus equal; NaN for the first w. */
  function rollingSpread(p, w) {
    return p.dates.map((_, i) => i < w ? NaN
      : (p.cap[i] / p.cap[i - w] - 1) - (p.equal[i] / p.equal[i - w] - 1));
  }

  /**
   * Concentration vs breadth days: +1 when cap-weight beat equal-weight on the session,
   * −1 when equal-weight won, 0 for an exact tie; running total from the window start.
   * The window's first day is scored against the session before it when there is one.
   */
  function dayScores(p, start = null) {
    const i0 = Math.max(startIndex(p, start), 1);
    const out = { dates: [], score: [], cum: [] };
    let run = 0;
    for (let i = i0; i < p.dates.length; i++) {
      const s = Math.sign((p.cap[i] / p.cap[i - 1]) - (p.equal[i] / p.equal[i - 1]));
      run += s;
      out.dates.push(p.dates[i]); out.score.push(s); out.cum.push(run);
    }
    return out;
  }

  /** z of the last value vs the trailing `lookback` window (pandas rolling, ddof=1). */
  function lastZscore(values, lookback) {
    const win = values.slice(Math.max(0, values.length - lookback)).filter((v) => Number.isFinite(v));
    const last = values[values.length - 1];
    if (!Number.isFinite(last) || win.length < Math.floor(lookback / 2) || win.length < 2) return NaN;
    const mean = win.reduce((a, b) => a + b, 0) / win.length;
    const sd = Math.sqrt(win.reduce((a, b) => a + (b - mean) ** 2, 0) / (win.length - 1));
    return (last - mean) / sd;
  }

  /** Where the last value sits in the whole series, 0-100. */
  function percentileRank(values) {
    const v = values.filter((x) => Number.isFinite(x));
    if (!v.length) return NaN;
    const last = v[v.length - 1];
    return v.filter((x) => x <= last).length / v.length * 100;
  }

  /**
   * Overwrite or append the live session's price (same rule as data.with_live_bar).
   * live: {SYM: {price, session}}. Returns a new pair-price object.
   */
  function withLive(p, pair, live) {
    const qc = live && live[pair.cap], qe = live && live[pair.equal];
    if (!qc && !qe) return p;
    const n = p.dates.length;
    const session = [qc, qe].filter(Boolean).map((q) => q.session).sort().pop();
    if (!session || (n && session < p.dates[n - 1])) return p;
    const out = { dates: p.dates.slice(), cap: p.cap.slice(), equal: p.equal.slice() };
    const capPx = qc && qc.session === session ? qc.price : out.cap[n - 1];
    const eqPx = qe && qe.session === session ? qe.price : out.equal[n - 1];
    if (n && session === p.dates[n - 1]) { out.cap[n - 1] = capPx; out.equal[n - 1] = eqPx; }
    else { out.dates.push(session); out.cap.push(capPx); out.equal.push(eqPx); }
    return out;
  }

  /** Raw close strictly before `session` from the build's history, or null. */
  function priorClose(hist, sym, session) {
    const c = hist.close[sym];
    if (!c) return null;
    for (let i = hist.dates.length - 1; i >= 0; i--) {
      if (hist.dates[i] < session && c[i] != null) return c[i];
    }
    return null;
  }

  /**
   * Intraday % vs prior close for both legs plus spread, on the union of bar times,
   * forward-filling the thinner leg. Returns {t: [epoch s], cap, equal, spread}.
   */
  function intradaySpread(hist, pair, live) {
    const qc = live && live[pair.cap], qe = live && live[pair.equal];
    const empty = { t: [], cap: [], equal: [], spread: [], session: null };
    if (!qc || !qe || !qc.bars || !qe.bars) return empty;
    const session = qc.session > qe.session ? qc.session : qe.session;
    if (qc.session !== session || qe.session !== session) return empty;
    const base = {
      cap: priorClose(hist, pair.cap, session) ?? qc.prevClose,
      equal: priorClose(hist, pair.equal, session) ?? qe.prevClose,
    };
    if (!base.cap || !base.equal) return empty;
    const mapOf = (b) => new Map(b.t.map((t, i) => [t, b.c[i]]));
    const mc = mapOf(qc.bars), me = mapOf(qe.bars);
    const ts = [...new Set([...qc.bars.t, ...qe.bars.t])].sort((a, b) => a - b);
    const out = { ...empty, session };
    let lc = null, le = null;
    for (const t of ts) {
      if (mc.get(t) != null) lc = mc.get(t);
      if (me.get(t) != null) le = me.get(t);
      if (lc == null || le == null) continue;
      const c = lc / base.cap - 1, e = le / base.equal - 1;
      out.t.push(t); out.cap.push(c); out.equal.push(e); out.spread.push(c - e);
    }
    return out;
  }

  /** One overview row, mirroring metrics.snapshot. */
  function snapshot(hist, pair, live, rollingWindow, zLookback) {
    const p = withLive(pairPrices(hist, pair), pair, live);
    const pr = periodReturns(p);
    const roll = rollingSpread(p, rollingWindow);
    const intra = intradaySpread(hist, pair, live);
    const k = intra.t.length - 1;
    return {
      id: pair.id,
      as_of: k >= 0 ? intra.t[k] : null,
      today_cap: k >= 0 ? intra.cap[k] : NaN,
      today_equal: k >= 0 ? intra.equal[k] : NaN,
      today_spread: k >= 0 ? intra.spread[k] : NaN,
      spread_1M: pr["1M"].spread, spread_YTD: pr["YTD"].spread, spread_1Y: pr["1Y"].spread,
      roll: roll[roll.length - 1],
      zscore: lastZscore(roll, zLookback),
      ratio_pctile: percentileRank(relativeRatio(p).values),
    };
  }

  return { PERIODS, subMonths, subDays, pairPrices, periodReturns, rebased, relativeRatio,
           rollingSpread, dayScores, lastZscore, percentileRank, withLive, priorClose, intradaySpread, snapshot };
})();

if (typeof module !== "undefined") module.exports = BN;
