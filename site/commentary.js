/**
 * The read: rule-based commentary on breadth and concentration, written in the page.
 *
 * Composed in the browser rather than at build time because the daily lane moves
 * with every live poll. Every figure in the text comes from the same BN functions
 * that draw the table and charts, so the prose cannot drift from the numbers.
 *
 * Interpretation follows the sign of the spread (cap-weighted minus equal-weighted):
 *   spread > 0  mega-caps ahead of the average stock = narrowing breadth / concentration
 *   spread < 0  the average stock ahead of the leaders = broadening
 * and, for the session, the direction of the cap-weighted index itself.
 *
 * Plain script (inlined by build_static.py); module.exports for the Node tests.
 */
const BNC = (() => {
  const B = typeof BN !== "undefined" ? BN : require("./metrics.js");

  const FLAT_BP = 10 / 1e4;      // |spread| below this on the day reads as "in line"
  const STALE_MIN = 10;          // a leg's last print older than this, market open, is flagged
  const SINCE_MIN_GAP = 20;      // only say "largest since" when that was 20+ sessions ago
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  // ---- formatting (text tokens only; the page escapes nothing here, so no user text) ----
  const fin = Number.isFinite;
  const sign = (x) => Math.abs(x) < 1e-12 ? "" : x > 0 ? "+" : "−";
  const pct = (x, dp = 2) => fin(x) ? sign(x) + Math.abs(x * 100).toFixed(dp) + "%" : "–";
  const pp = (x, dp = 1) => fin(x) ? sign(x) + Math.abs(x * 100).toFixed(dp) + "pp" : "–";
  const bp = (x) => fin(x) ? sign(x) + Math.abs(Math.round(x * 1e4)) + " bp" : "–";
  const sig = (z) => fin(z) ? Math.abs(z).toFixed(1) + "σ" : "–";
  const dLabel = (s) => { const [y, m, d] = s.split("-"); return `${+d} ${MONTHS[+m - 1]} ${y}`; };
  const nyDate = (epoch) => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York",
    year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(epoch * 1000));
  const nyHM = (epoch) => new Intl.DateTimeFormat("en-GB", { timeZone: "America/New_York",
    hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(epoch * 1000));
  const range = (xs, f) => { const v = xs.filter(fin).sort((a, b) => a - b);
    return v.length ? (v.length === 1 ? f(v[0]) : `${f(v[0])} to ${f(v[v.length - 1])}`) : "–"; };
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  // ---- statistics ----
  /** One-session return spread, cap − equal, per date (NaN for the first). */
  function dailySpreads(p) {
    return p.dates.map((_, i) => i === 0 ? NaN
      : (p.cap[i] / p.cap[i - 1] - 1) - (p.equal[i] / p.equal[i - 1] - 1));
  }

  /** z of `x` against the `lookback` values before index i (ddof 1). */
  function zVsPrior(values, i, x, lookback = 252) {
    const w = values.slice(Math.max(0, i - lookback), i).filter(fin);
    if (w.length < 60) return NaN;
    const m = w.reduce((a, b) => a + b, 0) / w.length;
    const sd = Math.sqrt(w.reduce((a, b) => a + (b - m) ** 2, 0) / (w.length - 1));
    return sd > 0 ? (x - m) / sd : NaN;
  }

  /**
   * The most recent j < i with the same sign as x and |values[j]| >= |x|.
   * {j, gap} or {j: -1, gap: i} when nothing in the history matches.
   */
  function largestSince(values, i, x) {
    for (let j = i - 1; j >= 0; j--) {
      const v = values[j];
      if (fin(v) && Math.sign(v) === Math.sign(x) && Math.abs(v) >= Math.abs(x)) return { j, gap: i - j };
    }
    return { j: -1, gap: i };
  }

  function sma(values, n) {
    if (values.length < n) return NaN;
    let s = 0; for (let k = values.length - n; k < values.length; k++) s += values[k];
    return s / n;
  }

  /** Long-run trend of the cap/equal ratio from its 50- and 200-session averages. */
  function ratioTrend(ratio) {
    const last = ratio[ratio.length - 1], m50 = sma(ratio, 50), m200 = sma(ratio, 200);
    if (!fin(m200)) return { key: "short", last, m50, m200 };
    let key;
    if (last >= m200 && m50 >= m200) key = last >= m50 ? "up" : "up_pullback";
    else if (last < m200 && m50 < m200) key = last < m50 ? "down" : "down_bounce";
    else key = last >= m200 ? "turning_up" : "turning_down";
    return { key, last, m50, m200 };
  }

  const TREND_TEXT = {
    up: "in a concentration uptrend: above its 50- and 200-day averages",
    up_pullback: "pulling back within a concentration uptrend: below its 50-day average but above its 200-day",
    down: "in a broadening downtrend: below its 50- and 200-day averages",
    down_bounce: "bouncing within a broadening trend: above its 50-day average but below its 200-day",
    turning_up: "turning towards concentration: back above its 200-day average while the 50-day is still below it",
    turning_down: "turning towards broadening: below its 200-day average while the 50-day is still above it",
    short: "too new for a 200-day trend read",
  };

  /** Session regime from the cap-weighted move and the spread. */
  function regime(capMove, spread) {
    if (!fin(spread) || Math.abs(spread) < FLAT_BP) return { key: "inline", text: "cap- and equal-weight moved in line" };
    if (spread > 0) return capMove >= 0
      ? { key: "narrow_rally", text: "a narrow rally led by the mega-caps" }
      : { key: "defensive", text: "mega-caps held up better than the average stock: defensive concentration" };
    return capMove >= 0
      ? { key: "broad_rally", text: "a broad rally, with the average stock outpacing the leaders" }
      : { key: "unwind", text: "the leaders sold hardest: concentration unwinding" };
  }

  function magnitudeWord(z) {
    if (!fin(z)) return "";
    const a = Math.abs(z);
    return a >= 3 ? "an exceptional" : a >= 2 ? "an unusually large" : a >= 1 ? "a sizeable" : "an ordinary-sized";
  }

  // ---- per-pair analysis ----
  function analysePair(hist, pair, quotes, settings, nowEpoch, marketOpen) {
    const p = B.withLive(B.pairPrices(hist, pair), pair, quotes);
    const n = p.dates.length;
    const out = { pair, n, start: p.dates[0] };
    if (n < 30) return out;

    // the session
    const intra = B.intradaySpread(hist, pair, quotes);
    const k = intra.t.length - 1;
    const ds = dailySpreads(p);
    if (k >= 0) {
      const spread = intra.spread[k], cap = intra.cap[k], eq = intra.equal[k];
      const iSess = p.dates.indexOf(intra.session);
      const i = iSess >= 0 ? iSess : n - 1;
      const z = zVsPrior(ds, i, spread);
      const since = largestSince(ds, i, spread);
      // intraday path: extreme of the same sign, and where it was
      let ext = 0, extAt = null;
      intra.spread.forEach((v, j) => { if (Math.sign(v) === Math.sign(spread) && Math.abs(v) > Math.abs(ext)) { ext = v; extAt = intra.t[j]; } });
      out.today = {
        session: intra.session, isToday: intra.session === nyDate(nowEpoch), asOf: intra.t[k],
        cap, equal: eq, spread, z, regime: regime(cap, spread),
        since: since.j >= 0 ? { date: p.dates[since.j], gap: since.gap } : { date: null, gap: since.gap },
        extreme: ext, extremeAt: extAt,
      };
    }

    // thin legs: last print stale while the market is open
    out.stale = [];
    if (marketOpen && out.today && out.today.isToday) {
      for (const sym of [pair.cap, pair.equal]) {
        const q = quotes && quotes[sym];
        if (q && fin(q.time) && (nowEpoch - q.time) / 60 > STALE_MIN) out.stale.push({ sym, mins: Math.round((nowEpoch - q.time) / 60) });
      }
    }

    // longer term
    const pr = B.periodReturns(p);
    const roll = B.rollingSpread(p, settings.rolling_window);
    const rLast = roll[n - 1];
    const rSince = largestSince(roll, n - 1, rLast);
    const ratio = B.relativeRatio(p).values;
    let peak = -Infinity, peakAt = 0;
    ratio.forEach((v, j) => { if (v > peak) { peak = v; peakAt = j; } });
    out.long = {
      pr, roll: rLast, rollZ: B.lastZscore(roll, settings.zscore_lookback),
      rollSince: rSince.j >= 0 ? { date: p.dates[rSince.j], gap: rSince.gap } : { date: null, gap: rSince.gap },
      pctile: B.percentileRank(ratio), trend: ratioTrend(ratio),
      fromPeak: ratio[n - 1] / peak - 1, peakDate: p.dates[peakAt],
    };
    return out;
  }

  // ---- composition ----
  function sinceText(s, start) {
    if (!s) return "";
    if (s.date === null) return `the largest in the data held (since ${dLabel(start)})`;
    return s.gap >= SINCE_MIN_GAP ? `the largest since ${dLabel(s.date)}` : "";
  }

  /**
   * Returns {headline, today: [line], longer: [line], notes: [line]}.
   * Inputs: hist, pairs (with optional duplicate_of), settings, quotes, nowEpoch, marketOpen.
   */
  function compose({ hist, pairs, settings, quotes, nowEpoch, marketOpen }) {
    const all = pairs.map((pr) => analysePair(hist, pr, quotes, settings, nowEpoch, marketOpen)).filter((a) => a.long);
    const prim = all.filter((a) => !a.pair.duplicate_of);
    const out = { headline: "", today: [], longer: [], notes: [] };
    if (!prim.length) { out.headline = "Not enough history to comment."; return out; }
    const lead = prim[0], N = prim.length;

    // ----- session lane -----
    const withDay = prim.filter((a) => a.today);
    let todayClause = "";
    if (withDay.length) {
      const t0 = lead.today || withDay[0].today;
      const when = t0.isToday ? "today" : `on ${dLabel(t0.session)}`;
      const neg = withDay.filter((a) => a.today.spread <= -FLAT_BP), pos = withDay.filter((a) => a.today.spread >= FLAT_BP);
      const spreads = withDay.map((a) => a.today.spread);
      if (neg.length === withDay.length) {
        out.today.push(`Equal-weight beat cap-weight in all ${withDay.length} indices ${when} (spreads ${range(spreads, bp)}): breadth broadening.`);
        todayClause = `The average stock beat the mega-caps across the board ${when}`;
      } else if (pos.length === withDay.length) {
        out.today.push(`Cap-weight beat equal-weight in all ${withDay.length} indices ${when} (spreads ${range(spreads, bp)}): breadth narrowing.`);
        todayClause = `Mega-caps led across the board ${when}`;
      } else {
        out.today.push(`Mixed ${when}: equal-weight ahead in ${plural(neg.length, "index", "indices")}, cap-weight ahead in ${pos.length}` +
          (withDay.length - neg.length - pos.length ? `, in line in ${withDay.length - neg.length - pos.length}` : "") +
          ` (spreads ${range(spreads, bp)}).`);
        todayClause = `Breadth was mixed ${when}`;
      }

      if (lead.today) {
        const t = lead.today, pn = lead.pair;
        let s = `${pn.name}: ${pn.cap} ${pct(t.cap)}, ${pn.equal} ${pct(t.equal)}, ${t.regime.text}.`;
        if (t.regime.key !== "inline" && fin(t.z)) {
          const st = sinceText(t.since, lead.start);
          s += ` At ${bp(t.spread)} this is ${magnitudeWord(t.z)} day for the spread (${sig(t.z)} against the past year)${st ? ", " + st : ""}.`;
        }
        out.today.push(s);
        if (t.isToday && t.extremeAt && t.regime.key !== "inline") {
          const ratio = Math.abs(t.spread) / Math.abs(t.extreme);
          if (ratio < 0.7) out.today.push(`The ${pn.name} spread has narrowed from ${bp(t.extreme)} at ${nyHM(t.extremeAt)} ET to ${bp(t.spread)}: the move is fading.`);
          else if (ratio > 0.95 && t.asOf - t.extremeAt < 30 * 60) out.today.push(`The ${pn.name} spread is at its widest of the session (${bp(t.spread)}): the move is still building.`);
        }
        todayClause += ` (${pn.name} ${bp(t.spread)}${fin(t.z) && Math.abs(t.z) >= 2 ? ", " + sig(t.z) : ""})`;
      }
      // the largest move outside the lead index, when it is the bigger story
      const big = withDay.filter((a) => a !== lead && fin(a.today.z)).sort((a, b) => Math.abs(b.today.z) - Math.abs(a.today.z))[0];
      if (big && Math.abs(big.today.z) >= 2 && (!lead.today || Math.abs(big.today.z) > Math.abs(lead.today.z || 0))) {
        const st = sinceText(big.today.since, big.start);
        out.today.push(`${big.pair.name} had the more extreme day: ${bp(big.today.spread)}, ${sig(big.today.z)}${st ? ", " + st : ""}.`);
      }
      for (const a of prim) for (const s of a.stale || []) {
        out.notes.push(`${s.sym} last traded ${s.mins} min ago, so the ${a.pair.name} intraday spread may lag.`);
      }
    } else {
      out.today.push("No intraday bars yet.");
    }

    // ----- longer-term lane -----
    const L = lead.long;
    out.longer.push(`${lead.pair.name} cap/equal ratio is ${TREND_TEXT[L.trend.key]}. ` +
      `It sits at the ${Math.round(L.pctile)}th percentile of its range since ${dLabel(lead.start)}` +
      (L.fromPeak < -0.005 ? `, ${pct(-L.fromPeak, 1).replace("+", "")} below its peak of ${dLabel(L.peakDate)}.` : ", at its peak."));

    const m1 = prim.map((a) => a.long.pr["1M"].spread).filter(fin);
    const m1neg = m1.filter((x) => x < 0).length;
    const extremeRoll = prim.slice().sort((a, b) => Math.abs(b.long.rollZ || 0) - Math.abs(a.long.rollZ || 0))[0];
    let monthLine = m1neg === m1.length ? `Over the past month equal-weight has outpaced cap-weight in all ${m1.length} indices (${range(m1, pp)}).`
      : m1neg === 0 ? `Over the past month cap-weight has outpaced equal-weight in all ${m1.length} indices (${range(m1, pp)}).`
      : `Over the past month equal-weight is ahead in ${m1neg} of ${m1.length} indices (${range(m1, pp)}).`;
    if (extremeRoll && fin(extremeRoll.long.rollZ) && Math.abs(extremeRoll.long.rollZ) >= 1.5) {
      const r = extremeRoll.long, st = r.rollSince.date === null ? `the most extreme in the data held (since ${dLabel(extremeRoll.start)})`
        : r.rollSince.gap >= SINCE_MIN_GAP ? `the most ${r.roll < 0 ? "broadening" : "concentrating"} since ${dLabel(r.rollSince.date)}` : "";
      monthLine += ` ${extremeRoll.pair.name}'s ${settings.rolling_window}-day spread of ${pp(r.roll)} is ${sig(r.rollZ)} from its one-year norm${st ? ", " + st : ""}.`;
    }
    out.longer.push(monthLine);

    const y1 = prim.filter((a) => fin(a.long.pr["1Y"].spread));
    if (y1.length) {
      const paid = y1.filter((a) => a.long.pr["1Y"].spread > 0);
      const lp = lead.long.pr;
      out.longer.push(`Return from holding ${lead.pair.cap} rather than ${lead.pair.equal}: ${pp(lp["1M"].spread)} over 1 month, ` +
        `${pp(lp["YTD"].spread)} year to date, ${pp(lp["1Y"].spread)} over 1 year (negative = cap-weighting cost money). ` +
        `Over 1 year cap-weighting has added value in ${paid.length} of ${y1.length} indices.`);
    }

    // ----- headline -----
    const longClause = L.pctile >= 70
      ? (L.trend.key.startsWith("up") || L.trend.key === "turning_up" ? "concentration remains high and trending up" : "concentration remains high, though the trend has turned")
      : L.pctile <= 30
        ? "concentration is low by its own history"
        : "concentration is mid-range by its own history";
    out.headline = (todayClause ? todayClause + "; " : "") + `${longClause} (${lead.pair.name} ratio at the ${Math.round(L.pctile)}th percentile).`;
    out.headline = out.headline.charAt(0).toUpperCase() + out.headline.slice(1);
    return out;
  }

  return { compose, analysePair, dailySpreads, zVsPrior, largestSince, ratioTrend, regime, FLAT_BP };
})();

if (typeof module !== "undefined") module.exports = BNC;
