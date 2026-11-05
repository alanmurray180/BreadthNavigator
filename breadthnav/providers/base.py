from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

NY = "America/New_York"


class Provider(ABC):
    """A market-data source.

    Contract (all providers must honour it so the metrics/dashboard stay source-agnostic):

    daily(symbols, start) -> DataFrame indexed by tz-naive session date, columns a
        MultiIndex (field, symbol) with fields:
            "close"      raw closing price (for intraday % change vs prior close)
            "adj_close"  split- and dividend-adjusted close (total-return basis)

    intraday(symbols, interval) -> DataFrame indexed by tz-aware America/New_York bar
        timestamps for the latest regular session, one column per symbol holding the
        bar's last traded price. Missing bars (illiquid ETFs) may be NaN.
    """

    name: str = "base"

    @abstractmethod
    def daily(self, symbols: list[str], start: str) -> pd.DataFrame: ...

    @abstractmethod
    def intraday(self, symbols: list[str], interval: str = "1m") -> pd.DataFrame: ...


def frame_from_series(series: dict[tuple[str, str], pd.Series]) -> pd.DataFrame:
    """Build a (field, symbol) MultiIndex frame from {(field, symbol): series}."""
    df = pd.DataFrame(series)
    df.columns = pd.MultiIndex.from_tuples(df.columns, names=["field", "symbol"])
    return df.sort_index()


def to_ny(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if index.tz is None:
        return index.tz_localize("UTC").tz_convert(NY)
    return index.tz_convert(NY)


def latest_session(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only bars from the most recent NY trading date in the frame."""
    if df.empty:
        return df
    dates = df.index.tz_convert(NY).normalize()
    return df[dates == dates.max()]


class ProviderError(RuntimeError):
    pass
