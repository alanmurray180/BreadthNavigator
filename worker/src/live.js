/**
 * Live 1-minute bars for the configured ETFs, from Yahoo's chart endpoint (keyless).
 *
 * The same module runs in two places so the parsing exists once:
 *   - the Worker's GET /live, which the page polls while it is open
 *   - worker/snapshot.mjs under Node in the build, baked into the page as the
 *     fallback when the Worker is unreachable, not yet deployed, or blocked
 *
 * Payload:
 *   { generated, source, quotes: { SYM: { price, prevClose, time, session,
 *                                        bars: { t: [epoch s], c: [price] } } },
 *     errors: [{ symbol, detail }] }
 * `session` is the New York trading date of the bars (YYYY-MM-DD).
 */

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36";

function chartUrl(host, sym) {
  return `https://${host}.finance.yahoo.com/v8/finance/chart/` +
    `${encodeURIComponent(sym)}?range=1d&interval=1m&includePrePost=false`;
}

export function nyDate(epochSeconds) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date(epochSeconds * 1000));
}

/** One symbol's chart, trying both Yahoo hosts; errors carry status + opening bytes. */
export async function fetchChart(sym, fetchImpl = fetch, extra = {}) {
  const tried = [];
  for (const host of ["query1", "query2"]) {
    try {
      const resp = await fetchImpl(chartUrl(host, sym), {
        headers: { "User-Agent": UA, Accept: "application/json" }, ...extra,
      });
      const text = await resp.text();
      if (!resp.ok) throw new Error(`${resp.status} ${text.slice(0, 120).replace(/\s+/g, " ")}`);
      const res = JSON.parse(text)?.chart?.result?.[0];
      if (!res) throw new Error("no result");
      return res;
    } catch (e) {
      tried.push(`${host}: ${e.message || e}`);
    }
  }
  throw new Error(tried.join(" | "));
}

/** Reduce a Yahoo chart result to the quote shape above. */
export function parseChart(res) {
  const meta = res.meta || {};
  const ts = res.timestamp || [];
  const closes = res.indicators?.quote?.[0]?.close || [];
  const t = [], c = [];
  ts.forEach((s, i) => {
    const v = closes[i];
    if (v != null && Number.isFinite(v)) { t.push(s); c.push(+v.toFixed(4)); }
  });
  const time = meta.regularMarketTime || (t.length ? t[t.length - 1] : null);
  const price = meta.regularMarketPrice ?? (c.length ? c[c.length - 1] : null);
  if (price == null || time == null) throw new Error("no price in chart");
  return {
    price,
    prevClose: meta.chartPreviousClose ?? meta.previousClose ?? null,
    time,
    session: nyDate(t.length ? t[t.length - 1] : time),
    bars: { t, c },
  };
}

export async function buildLive(symbols, source, fetchImpl = fetch, extra = {}) {
  const quotes = {}, errors = [];
  await Promise.all(symbols.map(async (sym) => {
    try {
      quotes[sym] = parseChart(await fetchChart(sym, fetchImpl, extra));
    } catch (e) {
      errors.push({ symbol: sym, detail: String(e.message || e).slice(0, 300) });
    }
  }));
  return { generated: new Date().toISOString(), source, quotes, errors };
}
