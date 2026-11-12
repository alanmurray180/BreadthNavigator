# BreadthNavigator

Tracks the return spread between cap-weighted and equal-weighted versions of an index
(starting with Nasdaq-100: **QQQM vs QQQE**) as close to real time as the data source allows.

**Spread = cap-weighted return − equal-weighted return.**
Positive = mega-caps leading (narrowing breadth / rising concentration).
Negative = the average stock leading (broadening).

## Live site (GitHub Pages)

`.github/workflows/pages.yml` builds `dist/index.html` (one self-contained page with the
daily history baked in) and deploys it to GitHub Pages on every push to `main`, on
`workflow_dispatch`, and on a backstop cron. The page polls the Cloudflare Worker in
[`worker/`](worker/README.md) for live 1-minute bars and recomputes every spread in the
browser with `site/metrics.js`, the JavaScript twin of `breadthnav/metrics.py`
(`tests/test_site.py` fails if the two disagree). Without the Worker the page still works,
showing the live snapshot taken at build time.

One-time setup:

1. Repo → Settings → Pages → Source: **GitHub Actions**.
2. Merge to `main` (the first push builds and deploys).
3. Deploy the Worker and set the `LIVE_URL` repository variable: see `worker/README.md`.

The build fails, and Pages keeps the previous version, if a required pair has no history or
the history is more than 4 business days old. An `optional: true` pair (e.g. `^NDX`/`^NDXE`)
is dropped with a warning instead.

## The read (commentary box)

`site/commentary.js` writes the box at the top of the page by rule, in the browser, from
the same functions that draw the table, so it updates with each live poll and every figure
in it is a figure on the page. Two lanes:

* **Session**: how many indices broadened or narrowed; the lead index's regime (narrow
  rally, broad rally, defensive concentration, concentration unwinding); the size of the
  day's spread in sigmas against the past year and the last time it was as large; whether
  the intraday move is building or fading; stale thin legs.
* **Longer term**: the cap/equal ratio's trend against its 50- and 200-day averages, its
  percentile and distance from peak; the past month across indices with the most extreme
  21-day spread; the return from holding cap- rather than equal-weight over 1M / YTD / 1Y.

Pairs with `duplicate_of` (the index-level Nasdaq pair) are left out of cross-index counts.
Thresholds are constants at the top of the file. Tests: `tests/js/commentary.test.mjs`.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py          # dashboard, auto-refreshes every 60s in US market hours
python -m breadthnav          # one-off snapshot in the terminal
python -m breadthnav --csv spread_log.csv   # append a snapshot (schedule with cron)
pytest -q                     # calculation + JS parity tests
node --test tests/js/*.test.mjs   # Worker tests
python scripts/build_static.py dist   # build the Pages site locally
```

## What the dashboard shows

* **All indices** – today's spread, 1M / YTD / 1Y spread, rolling 21-day spread, its z-score
  vs the trailing year, and where the cap/equal ratio sits in its own history.
* **Detail** – intraday % vs prior close for both legs, intraday spread, period-return table,
  cumulative total return, relative ratio and rolling spread history, and a
  concentration-vs-breadth day count (+1 when cap-weight beat equal-weight on the day,
  −1 when it lagged, with the running total from the start of the chosen window).

## Data sources

| Provider | Key | Latency | Notes |
|---|---|---|---|
| `yahoo` (default) | none | ~real-time, 1-min bars | Unofficial API via `yfinance`; fine for monitoring, can rate-limit or break. |
| `alpaca` | `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` | Free: real-time IEX only. Paid (~$99/mo): real-time consolidated tape | Official API. IEX is thin for QQQE, so its free real-time prints are patchy. Set `ALPACA_FEED=sip` on a paid plan. |
| `fmp` | `FMP_API_KEY` | Real-time on paid tiers | Quote/chart endpoints need a higher plan than the one currently connected. |

Pick with the sidebar, `settings.provider` in `config/pairs.yaml`, or `BREADTHNAV_PROVIDER`.

## Adding an index

Append a pair to `config/pairs.yaml`:

```yaml
  - id: msci_world
    name: MSCI World
    cap: URTH
    equal: <equal-weight ticker>
```

Use `providers: [yahoo]` to restrict a pair to sources that carry its symbols (e.g. index levels
such as `^NDX` / `^NDXE`). For the Pages site, also add any new symbols to `SYMBOLS` in `worker/wrangler.toml`.
A new data source = one class implementing `Provider.daily` and
`Provider.intraday` (see `breadthnav/providers/base.py`) plus one line in the registry.

## Method notes

* History uses dividend-adjusted closes (total return); intraday uses raw prices vs the prior raw close,
  so an ex-dividend day shows the dividend drop until the daily data refreshes.
* Thin intraday bars (QQQE) are forward-filled so each minute compares like with like.
* ETF spreads include the fee differential (QQQM 0.15% vs QQQE 0.35% ≈ 20 bp/yr) and any premium/discount;
  the index-level pair (`^NDX` vs `^NDXE`, price return) strips both out.
* Market-hours detection ignores US holidays (it just refreshes with no new bars).
