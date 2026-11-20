from __future__ import annotations

import sys
import time

import pandas as pd

from .base import Provider, ProviderError, frame_from_series, latest_session, to_ny

# Waits (seconds) before each retry of symbols that came back empty.
RETRY_WAITS = (2, 5, 10)


class YahooProvider(Provider):
    """Yahoo Finance via yfinance. Free, no key, roughly real-time for US-listed ETFs.

    Unofficial API: fine for monitoring, but rate-limited and can break without notice.

    Downloads run single-threaded. With threads=True, yfinance's worker threads share
    its SQLite cache and intermittently lose one symbol to "database is locked"; in
    Nov 2026 that failed about one Pages build in six. Any symbol that still comes back
    empty is retried on its own, with backoff, before the build is allowed to fail.
    """

    name = "yahoo"

    def __init__(self) -> None:
        import yfinance  # imported lazily so other providers don't need it

        self._yf = yfinance
        self._sleep = time.sleep

    def _fetch(self, symbols: list[str], **kw) -> pd.DataFrame | None:
        return self._yf.download(
            symbols, auto_adjust=False, actions=False, progress=False,
            group_by="column", multi_level_index=True, threads=False, **kw,
        )

    @staticmethod
    def _missing(df: pd.DataFrame | None, symbols: list[str]) -> list[str]:
        if df is None or df.empty:
            return list(symbols)
        return [s for s in symbols
                if ("Close", s) not in df.columns or df[("Close", s)].isna().all()]

    def _download(self, symbols: list[str], **kw) -> pd.DataFrame:
        df = self._fetch(symbols, **kw)
        missing = self._missing(df, symbols)
        for wait in RETRY_WAITS:
            if not missing:
                break
            print(f"yahoo: retrying {missing} in {wait}s", file=sys.stderr)
            self._sleep(wait)
            for sym in list(missing):
                one = self._fetch([sym], **kw)
                if self._missing(one, [sym]):
                    continue
                keep = df.drop(columns=[c for c in df.columns if c[1] == sym]) \
                    if df is not None and not df.empty else None
                df = one if keep is None else pd.concat([keep, one], axis=1)
                missing.remove(sym)
        if df is None or df.empty:
            raise ProviderError(f"Yahoo returned no data for {symbols}")
        if missing:
            print(f"yahoo: still no data for {missing} after {len(RETRY_WAITS)} retries",
                  file=sys.stderr)
        return df

    def _col(self, df: pd.DataFrame, field: str, sym: str) -> pd.Series:
        """A column, or an all-NaN series if Yahoo never returned the symbol."""
        if (field, sym) in df.columns:
            return df[(field, sym)]
        return pd.Series(float("nan"), index=df.index)

    def daily(self, symbols: list[str], start: str) -> pd.DataFrame:
        df = self._download(symbols, start=start, interval="1d")
        out = {}
        for sym in symbols:
            out[("close", sym)] = self._col(df, "Close", sym)
            out[("adj_close", sym)] = self._col(df, "Adj Close", sym)
        frame = frame_from_series(out)
        frame.index = pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
        return frame.dropna(how="all")

    def intraday(self, symbols: list[str], interval: str = "1m") -> pd.DataFrame:
        # period=5d so that pre-market / weekends still return the last full session
        df = self._download(symbols, period="5d", interval=interval, prepost=False)
        close = pd.DataFrame({s: self._col(df, "Close", s) for s in symbols})
        close.index = to_ny(pd.DatetimeIndex(close.index))
        return latest_session(close.dropna(how="all"))
