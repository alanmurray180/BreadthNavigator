from __future__ import annotations

import pandas as pd

from .base import Provider, ProviderError, frame_from_series, latest_session, to_ny


class YahooProvider(Provider):
    """Yahoo Finance via yfinance. Free, no key, roughly real-time for US-listed ETFs.

    Unofficial API: fine for monitoring, but rate-limited and can break without notice.
    """

    name = "yahoo"

    def __init__(self) -> None:
        import yfinance  # imported lazily so other providers don't need it

        self._yf = yfinance

    def _download(self, symbols: list[str], **kw) -> pd.DataFrame:
        df = self._yf.download(
            symbols, auto_adjust=False, actions=False, progress=False,
            group_by="column", multi_level_index=True, threads=True, **kw,
        )
        if df is None or df.empty:
            raise ProviderError(f"Yahoo returned no data for {symbols}")
        return df

    def daily(self, symbols: list[str], start: str) -> pd.DataFrame:
        df = self._download(symbols, start=start, interval="1d")
        out = {}
        for sym in symbols:
            out[("close", sym)] = df["Close"][sym]
            out[("adj_close", sym)] = df["Adj Close"][sym]
        frame = frame_from_series(out)
        frame.index = pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
        return frame.dropna(how="all")

    def intraday(self, symbols: list[str], interval: str = "1m") -> pd.DataFrame:
        # period=5d so that pre-market / weekends still return the last full session
        df = self._download(symbols, period="5d", interval=interval, prepost=False)
        close = df["Close"][symbols].copy()
        close.index = to_ny(pd.DatetimeIndex(close.index))
        return latest_session(close.dropna(how="all"))
