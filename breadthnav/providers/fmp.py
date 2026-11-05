from __future__ import annotations

import os

import pandas as pd
import requests

from .base import NY, Provider, ProviderError, frame_from_series, latest_session

BASE = "https://financialmodelingprep.com/stable"


class FMPProvider(Provider):
    """Financial Modeling Prep (stable API).

    Env: FMP_API_KEY. Intraday charts and dividend-adjusted history need a paid tier;
    the current account tier was refused for quote/chart endpoints during set-up.
    """

    name = "fmp"

    def __init__(self) -> None:
        self.key = os.environ.get("FMP_API_KEY")
        if not self.key:
            raise ProviderError("Set FMP_API_KEY")
        self.session = requests.Session()

    def _get(self, path: str, **params) -> list[dict]:
        params["apikey"] = self.key
        r = self.session.get(f"{BASE}/{path}", params=params, timeout=30)
        if r.status_code != 200:
            raise ProviderError(f"FMP {path} {r.status_code}: {r.text[:200]}")
        data = r.json()
        if isinstance(data, dict):  # error payloads come back as objects
            raise ProviderError(f"FMP {path}: {data}")
        return data

    def daily(self, symbols: list[str], start: str) -> pd.DataFrame:
        series = {}
        for sym in symbols:
            raw = pd.DataFrame(self._get("historical-price-eod/full", symbol=sym, **{"from": start}))
            adj = pd.DataFrame(self._get("historical-price-eod/dividend-adjusted", symbol=sym, **{"from": start}))
            if raw.empty or adj.empty:
                raise ProviderError(f"FMP returned no daily data for {sym}")
            series[("close", sym)] = raw.set_index(pd.to_datetime(raw["date"]))["close"]
            series[("adj_close", sym)] = adj.set_index(pd.to_datetime(adj["date"]))["adjClose"]
        return frame_from_series(series)

    def intraday(self, symbols: list[str], interval: str = "1m") -> pd.DataFrame:
        tf = {"1m": "1min", "5m": "5min", "15m": "15min"}[interval]
        cols = {}
        for sym in symbols:
            rows = pd.DataFrame(self._get(f"historical-chart/{tf}", symbol=sym))
            if rows.empty:
                raise ProviderError(f"FMP returned no intraday data for {sym}")
            idx = pd.to_datetime(rows["date"]).dt.tz_localize(NY)  # FMP timestamps are ET
            cols[sym] = pd.Series(rows["close"].to_numpy(), index=idx)
        df = pd.DataFrame(cols).sort_index()
        return latest_session(df)
