"""Fetch once for every pair - one batched call per provider, not one per pair."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import Pair
from .providers import Provider


@dataclass
class MarketData:
    daily: pd.DataFrame
    intraday: pd.DataFrame | None
    errors: dict[str, str] = field(default_factory=dict)

    def has(self, pair: Pair) -> bool:
        try:
            return all(self.daily[("adj_close", s)].notna().sum() > 1 for s in pair.symbols)
        except KeyError:
            return False


def unique_symbols(pairs: list[Pair]) -> list[str]:
    return list(dict.fromkeys(s for p in pairs for s in p.symbols))


def fetch(provider: Provider, pairs: list[Pair], start: str, interval: str) -> MarketData:
    symbols = unique_symbols(pairs)
    daily = provider.daily(symbols, start)
    errors: dict[str, str] = {}
    try:
        intraday = provider.intraday(symbols, interval)
    except Exception as exc:  # intraday is best-effort; history still renders
        intraday, errors["intraday"] = None, str(exc)
    md = MarketData(daily=daily, intraday=intraday, errors=errors)
    for p in pairs:
        if not md.has(p):
            md.errors[p.id] = f"no price history for {p.cap} and/or {p.equal} from {provider.name}"
    return md


def with_live_bar(daily: pd.DataFrame, intraday: pd.DataFrame | None) -> pd.DataFrame:
    """Overwrite/append today's daily row with the latest intraday price.

    Keeps period returns (1D, 1W, YTD...) live between slower daily refreshes. Today's
    adjusted close is set to the raw price - exact except on an ex-dividend day.
    """
    if intraday is None or intraday.empty:
        return daily
    last = intraday.ffill().iloc[-1].dropna()
    session = intraday.index[-1].tz_localize(None).normalize()
    out = daily.copy()
    if session not in out.index:
        out.loc[session] = float("nan")
    for sym, px in last.items():
        for f in ("close", "adj_close"):
            if (f, sym) in out.columns:
                out.loc[session, (f, sym)] = px
    return out.sort_index()
