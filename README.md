# BreadthNavigator

Tracks the return spread between cap-weighted and equal-weighted versions of an index
(starting with Nasdaq-100: **QQQM vs QQQE**) as close to real time as the data source allows.

**Spread = cap-weighted return − equal-weighted return.**
Positive = mega-caps leading (narrowing breadth / rising concentration).
Negative = the average stock leading (broadening).

## Run

```bash
pip install -r requirements.txt
streamlit run app.py          # dashboard, auto-refreshes every 60s in US market hours
python -m breadthnav          # one-off snapshot in the terminal
python -m breadthnav --csv spread_log.csv   # append a snapshot (schedule with cron)
pytest -q                     # calculation tests
```

## What the dashboard shows

* **All indices** – today's spread, 1M / YTD / 1Y spread, rolling 21-day spread, its z-score
  vs the trailing year, and where the cap/equal ratio sits in its own history.
* **Detail** – intraday % vs prior close for both legs, intraday spread, period-return table,
  cumulative total return, relative ratio and rolling spread history.

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
such as `^NDX` / `^NDXE`). A new data source = one class implementing `Provider.daily` and
`Provider.intraday` (see `breadthnav/providers/base.py`) plus one line in the registry.

## Method notes

* History uses dividend-adjusted closes (total return); intraday uses raw prices vs the prior raw close,
  so an ex-dividend day shows the dividend drop until the daily data refreshes.
* Thin intraday bars (QQQE) are forward-filled so each minute compares like with like.
* ETF spreads include the fee differential (QQQM 0.15% vs QQQE 0.35% ≈ 20 bp/yr) and any premium/discount;
  the index-level pair (`^NDX` vs `^NDXE`, price return) strips both out.
* Market-hours detection ignores US holidays (it just refreshes with no new bars).
