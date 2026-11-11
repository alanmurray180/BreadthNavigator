"""Pure calculations. No I/O - every function takes DataFrames and returns DataFrames.

Conventions
-----------
* "cap" = cap-weighted leg, "equal" = equal-weighted leg.
* Returns are decimals (0.012 = 1.2%). Spread = cap return - equal return.
* Long-horizon metrics use adjusted (total-return) closes; intraday uses raw prices
  against the prior session's raw close (same basis as a quote screen).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Pair

PERIODS = ["1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "3Y", "Since start"]
_OFFSETS = {
    "1W": pd.DateOffset(weeks=1), "1M": pd.DateOffset(months=1),
    "3M": pd.DateOffset(months=3), "6M": pd.DateOffset(months=6),
    "1Y": pd.DateOffset(years=1), "3Y": pd.DateOffset(years=3),
}


def pair_prices(daily: pd.DataFrame, pair: Pair, field: str = "adj_close") -> pd.DataFrame:
    """Two-column frame (cap, equal) on the dates both legs have a price."""
    df = pd.DataFrame({"cap": daily[(field, pair.cap)], "equal": daily[(field, pair.equal)]})
    return df.dropna()


def _base_value(prices: pd.DataFrame, period: str) -> pd.Series | None:
    end = prices.index[-1]
    if period == "1D":
        return prices.iloc[-2] if len(prices) > 1 else None
    if period == "Since start":
        return prices.iloc[0]
    if period == "YTD":
        prior = prices[prices.index < pd.Timestamp(year=end.year, month=1, day=1)]
    else:
        prior = prices[prices.index <= end - _OFFSETS[period]]
    return prior.iloc[-1] if len(prior) else None


def period_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Rows = periods, columns = cap, equal, spread. Periods without full history are NaN."""
    last = prices.iloc[-1]
    rows = {}
    for p in PERIODS:
        base = _base_value(prices, p)
        if base is None:
            rows[p] = {"cap": np.nan, "equal": np.nan}
        else:
            r = last / base - 1
            rows[p] = {"cap": r["cap"], "equal": r["equal"]}
    out = pd.DataFrame.from_dict(rows, orient="index")
    out["spread"] = out["cap"] - out["equal"]
    return out


def relative_ratio(prices: pd.DataFrame, start: pd.Timestamp | None = None) -> pd.Series:
    """Cap/equal total-return ratio rebased to 100. Rising = cap-weighted outperforming."""
    p = prices if start is None else prices[prices.index >= start]
    rebased = p / p.iloc[0]
    return (rebased["cap"] / rebased["equal"] * 100).rename("ratio")


def rebased(prices: pd.DataFrame, start: pd.Timestamp | None = None) -> pd.DataFrame:
    p = prices if start is None else prices[prices.index >= start]
    return p / p.iloc[0] * 100


def rolling_spread(prices: pd.DataFrame, window: int) -> pd.Series:
    """Trailing `window`-session return of cap minus equal."""
    r = prices.pct_change(window, fill_method=None)
    return (r["cap"] - r["equal"]).rename(f"spread_{window}d")


def day_scores(prices: pd.DataFrame, start: pd.Timestamp | None = None) -> pd.DataFrame:
    """+1 on sessions where cap-weight beat equal-weight (concentration), -1 where
    equal-weight won (breadth), 0 for an exact tie; `cum` is the running total from
    the window start. The first day of the window is scored against the day before it."""
    rel = prices["cap"] / prices["cap"].shift() - prices["equal"] / prices["equal"].shift()
    score = np.sign(rel).iloc[1:]
    if start is not None:
        score = score[score.index >= start]
    return pd.DataFrame({"score": score.astype(int), "cum": score.cumsum().astype(int)})


def zscore(series: pd.Series, lookback: int) -> pd.Series:
    mean = series.rolling(lookback, min_periods=lookback // 2).mean()
    std = series.rolling(lookback, min_periods=lookback // 2).std()
    return ((series - mean) / std).rename("zscore")


def percentile_rank(series: pd.Series) -> float:
    """Where the latest value sits in the series' full history, 0-100."""
    s = series.dropna()
    if s.empty:
        return float("nan")
    return float((s <= s.iloc[-1]).mean() * 100)


def prior_close(daily: pd.DataFrame, symbol: str, session_date: pd.Timestamp) -> float:
    closes = daily[("close", symbol)].dropna()
    before = closes[closes.index < session_date.normalize()]
    if before.empty:
        raise ValueError(f"no close for {symbol} before {session_date.date()}")
    return float(before.iloc[-1])


def intraday_spread(intraday: pd.DataFrame, daily: pd.DataFrame, pair: Pair) -> pd.DataFrame:
    """Per-bar % change vs prior close for both legs plus the spread.

    Gaps in the thinner leg are forward-filled so each bar compares like with like.
    """
    bars = intraday[[pair.cap, pair.equal]].sort_index().ffill().dropna()
    if bars.empty:
        return pd.DataFrame(columns=["cap", "equal", "spread"])
    session = bars.index[-1].tz_localize(None).normalize()
    base = {s: prior_close(daily, s, session) for s in (pair.cap, pair.equal)}
    out = pd.DataFrame({
        "cap": bars[pair.cap] / base[pair.cap] - 1,
        "equal": bars[pair.equal] / base[pair.equal] - 1,
    })
    out["spread"] = out["cap"] - out["equal"]
    return out


def snapshot(pair: Pair, daily: pd.DataFrame, intraday: pd.DataFrame | None,
             rolling_window: int, zscore_lookback: int) -> dict:
    """One overview row for a pair."""
    prices = pair_prices(daily, pair)
    pr = period_returns(prices)
    roll = rolling_spread(prices, rolling_window)
    z = zscore(roll, zscore_lookback)
    row = {
        "pair": pair.name, "cap": pair.cap, "equal": pair.equal,
        "as_of": None, "today_cap": np.nan, "today_equal": np.nan, "today_spread": np.nan,
    }
    if intraday is not None and not intraday.empty:
        intra = intraday_spread(intraday, daily, pair)
        if not intra.empty:
            last = intra.iloc[-1]
            row.update(as_of=intra.index[-1], today_cap=last["cap"],
                       today_equal=last["equal"], today_spread=last["spread"])
    for p in ("1M", "YTD", "1Y"):
        row[f"spread_{p}"] = pr.loc[p, "spread"]
    row[f"roll_{rolling_window}d"] = roll.iloc[-1] if len(roll) else np.nan
    row["zscore"] = z.iloc[-1] if len(z) else np.nan
    row["ratio_pctile"] = percentile_rank(relative_ratio(prices))
    return row
