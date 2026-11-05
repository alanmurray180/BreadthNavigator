from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from .base import NY, Provider, ProviderError, frame_from_series, latest_session, to_ny

BASE = "https://data.alpaca.markets/v2/stocks/bars"


class AlpacaProvider(Provider):
    """Alpaca Market Data (official, documented API).

    Env: ALPACA_API_KEY_ID, ALPACA_API_SECRET_KEY, optional ALPACA_FEED (iex | sip).
    Free plan: real-time from IEX only (thin for low-volume ETFs such as QQQE),
    SIP consolidated tape only if older than 15 minutes. Paid plan: real-time SIP.
    """

    name = "alpaca"

    def __init__(self) -> None:
        key = os.environ.get("ALPACA_API_KEY_ID")
        secret = os.environ.get("ALPACA_API_SECRET_KEY")
        if not key or not secret:
            raise ProviderError("Set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY")
        self.feed = os.environ.get("ALPACA_FEED", "iex")
        self.session = requests.Session()
        self.session.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})

    def _bars(self, symbols: list[str], timeframe: str, start: str,
              adjustment: str, feed: str) -> dict[str, pd.DataFrame]:
        params = {"symbols": ",".join(symbols), "timeframe": timeframe, "start": start,
                  "adjustment": adjustment, "feed": feed, "limit": 10000}
        bars: dict[str, list] = {s: [] for s in symbols}
        while True:
            r = self.session.get(BASE, params=params, timeout=30)
            if r.status_code != 200:
                raise ProviderError(f"Alpaca {r.status_code}: {r.text[:200]}")
            body = r.json()
            for sym, rows in (body.get("bars") or {}).items():
                bars.setdefault(sym, []).extend(rows)
            token = body.get("next_page_token")
            if not token:
                break
            params["page_token"] = token
        out = {}
        for sym, rows in bars.items():
            if rows:
                df = pd.DataFrame(rows)
                df.index = pd.to_datetime(df["t"], utc=True)
                out[sym] = df
        return out

    def daily(self, symbols: list[str], start: str) -> pd.DataFrame:
        # Daily history via SIP is permitted on the free plan (data > 15 min old).
        hist_feed = "sip"
        raw = self._bars(symbols, "1Day", start, "raw", hist_feed)
        adj = self._bars(symbols, "1Day", start, "all", hist_feed)
        series = {}
        for sym in symbols:
            if sym not in raw:
                raise ProviderError(f"Alpaca returned no daily bars for {sym}")
            series[("close", sym)] = raw[sym]["c"]
            series[("adj_close", sym)] = adj[sym]["c"]
        frame = frame_from_series(series)
        frame.index = frame.index.tz_convert(NY).tz_localize(None).normalize()
        return frame

    def intraday(self, symbols: list[str], interval: str = "1m") -> pd.DataFrame:
        tf = {"1m": "1Min", "5m": "5Min", "15m": "15Min"}[interval]
        start = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        bars = self._bars(symbols, tf, start, "raw", self.feed)
        df = pd.DataFrame({s: bars[s]["c"] for s in symbols if s in bars})
        if df.empty:
            raise ProviderError(f"Alpaca returned no intraday bars for {symbols}")
        df.index = to_ny(pd.DatetimeIndex(df.index))
        # regular session only
        df = df.between_time("09:30", "15:59")
        return latest_session(df)
