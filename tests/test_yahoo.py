"""YahooProvider retry logic, against a stand-in for yfinance.download."""
import numpy as np
import pandas as pd
import pytest

from breadthnav.providers.base import ProviderError
from breadthnav.providers.yahoo import RETRY_WAITS, YahooProvider

IDX = pd.bdate_range("2026-01-02", periods=5)


def yf_frame(symbols, empty=()):
    """Shape of yf.download(group_by='column', multi_level_index=True): (Price, Ticker)."""
    cols, data = [], {}
    for field in ("Adj Close", "Close"):
        for s in symbols:
            cols.append((field, s))
            data[(field, s)] = [np.nan] * len(IDX) if s in empty else [100.0 + i for i in range(len(IDX))]
    df = pd.DataFrame(data, index=IDX)
    df.columns = pd.MultiIndex.from_tuples(cols, names=["Price", "Ticker"])
    return df


class FakeYF:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def download(self, symbols, **kw):
        self.calls.append((list(symbols), kw["threads"]))
        return self.script.pop(0)(symbols)


def provider(script):
    p = YahooProvider.__new__(YahooProvider)
    p._yf, p.slept = FakeYF(script), []
    p._sleep = p.slept.append
    return p


def test_locked_symbol_is_retried_alone_and_merged():
    p = provider([lambda s: yf_frame(s, empty={"RSP"}),   # 'database is locked' on RSP
                  lambda s: yf_frame(s)])
    out = p.daily(["SPY", "RSP"], "2026-01-01")
    assert out[("adj_close", "RSP")].notna().all() and out[("adj_close", "SPY")].notna().all()
    assert p._yf.calls == [(["SPY", "RSP"], False), (["RSP"], False)]  # single-threaded
    assert p.slept == [RETRY_WAITS[0]]


def test_gives_up_after_retries_and_leaves_symbol_empty():
    p = provider([lambda s: yf_frame(s, empty={"QQQE"})] +
                 [lambda s: yf_frame(s, empty={"QQQE"})] * len(RETRY_WAITS))
    out = p.daily(["QQQM", "QQQE"], "2026-01-01")
    assert out[("adj_close", "QQQE")].isna().all()  # build_static then blocks the pair
    assert p.slept == list(RETRY_WAITS)


def test_symbol_missing_from_columns_entirely():
    p = provider([lambda s: yf_frame([x for x in s if x != "DIA"]), lambda s: yf_frame(s)])
    out = p.daily(["DIA", "EDOW"], "2026-01-01")
    assert out[("close", "DIA")].notna().all()


def test_total_failure_raises():
    p = provider([lambda s: pd.DataFrame()] * (1 + len(RETRY_WAITS) * 2))
    with pytest.raises(ProviderError):
        p.daily(["SPY", "RSP"], "2026-01-01")
