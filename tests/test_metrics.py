"""Calculation tests on hand-built prices with known answers."""
import numpy as np
import pandas as pd
import pytest

from breadthnav import metrics as m
from breadthnav.config import Pair, load_config
from breadthnav.data import unique_symbols, with_live_bar
from breadthnav.providers.base import frame_from_series

PAIR = Pair(id="t", name="Test", cap="CAP", equal="EQ")


def make_daily(cap, eq, start="2024-01-02", raw_cap=None, raw_eq=None):
    idx = pd.bdate_range(start, periods=len(cap))
    return frame_from_series({
        ("close", "CAP"): pd.Series(raw_cap if raw_cap is not None else cap, idx, dtype=float),
        ("adj_close", "CAP"): pd.Series(cap, idx, dtype=float),
        ("close", "EQ"): pd.Series(raw_eq if raw_eq is not None else eq, idx, dtype=float),
        ("adj_close", "EQ"): pd.Series(eq, idx, dtype=float),
    })


def test_period_returns_1d_and_since_start():
    d = make_daily([100, 110, 121], [100, 100, 105])
    pr = m.period_returns(m.pair_prices(d, PAIR))
    assert pr.loc["1D", "cap"] == pytest.approx(0.10)
    assert pr.loc["1D", "equal"] == pytest.approx(0.05)
    assert pr.loc["1D", "spread"] == pytest.approx(0.05)
    assert pr.loc["Since start", "spread"] == pytest.approx(0.21 - 0.05)
    assert np.isnan(pr.loc["1Y", "spread"])  # not enough history


def test_ytd_uses_prior_year_close():
    idx = pd.to_datetime(["2024-12-30", "2024-12-31", "2025-01-02", "2025-01-03"])
    d = frame_from_series({(f, s): pd.Series(v, idx, dtype=float)
                           for f in ("close", "adj_close")
                           for s, v in (("CAP", [90, 100, 102, 110]), ("EQ", [90, 100, 101, 99]))})
    pr = m.period_returns(m.pair_prices(d, PAIR))
    assert pr.loc["YTD", "cap"] == pytest.approx(0.10)
    assert pr.loc["YTD", "equal"] == pytest.approx(-0.01)


def test_pair_prices_drops_dates_before_both_legs_trade():
    d = make_daily([100, 101, 102, 103], [np.nan, np.nan, 50, 51])
    p = m.pair_prices(d, PAIR)
    assert len(p) == 2 and p.index[0] == d.index[2]


def test_relative_ratio_and_rolling_spread():
    d = make_daily([100, 110, 121, 133.1], [100, 100, 100, 100])
    prices = m.pair_prices(d, PAIR)
    ratio = m.relative_ratio(prices)
    assert ratio.iloc[0] == 100 and ratio.iloc[-1] == pytest.approx(133.1)
    roll = m.rolling_spread(prices, 2)
    assert roll.iloc[-1] == pytest.approx(133.1 / 110 - 1)


def test_zscore_of_constant_then_jump():
    s = pd.Series([0.0, 1.0] * 50 + [5.0])
    z = m.zscore(s, 100)
    assert z.iloc[-1] > 3


def test_intraday_spread_uses_raw_prior_close_and_ffills_thin_leg():
    # adj closes differ from raw (dividend adjustment) - intraday must use raw
    d = make_daily([99, 100], [49, 50], start="2025-03-03", raw_cap=[100, 100], raw_eq=[50, 50])
    ts = pd.date_range("2025-03-05 09:30", periods=3, freq="min", tz="America/New_York")
    intra = pd.DataFrame({"CAP": [101.0, 102.0, 103.0], "EQ": [50.5, np.nan, 49.5]}, index=ts)
    out = m.intraday_spread(intra, d, PAIR)
    assert out["cap"].iloc[-1] == pytest.approx(0.03)
    assert out["equal"].iloc[1] == pytest.approx(0.01)  # forward-filled
    assert out["spread"].iloc[-1] == pytest.approx(0.03 - (-0.01))


def test_with_live_bar_appends_session_row():
    d = make_daily([100, 101], [50, 51], start="2025-03-03")
    ts = pd.date_range("2025-03-05 15:58", periods=2, freq="min", tz="America/New_York")
    intra = pd.DataFrame({"CAP": [102.0, 103.0], "EQ": [52.0, np.nan]}, index=ts)
    live = with_live_bar(d, intra)
    assert live.index[-1] == pd.Timestamp("2025-03-05")
    assert live[("adj_close", "CAP")].iloc[-1] == 103.0
    assert live[("close", "EQ")].iloc[-1] == 52.0  # last non-NaN bar


def test_snapshot_row():
    n = 300
    rng = np.random.default_rng(0)
    cap = 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))
    eq = 100 * np.cumprod(1 + rng.normal(0.0003, 0.01, n))
    d = make_daily(cap, eq)
    row = m.snapshot(PAIR, d, None, 21, 252)
    assert row["today_spread"] is np.nan or np.isnan(row["today_spread"])
    assert not np.isnan(row["spread_1M"]) and 0 <= row["ratio_pctile"] <= 100


def test_shipped_config_loads_and_symbols_dedupe():
    cfg = load_config()
    ids = [p.id for p in cfg.pairs]
    assert "ndx100" in ids and len(ids) == len(set(ids))
    assert cfg.pair("ndx100").symbols == ["QQQM", "QQQE"]
    assert all(p.id != "ndx100_index" for p in cfg.pairs_for("alpaca"))
    syms = unique_symbols(list(cfg.pairs))
    assert len(syms) == len(set(syms))
