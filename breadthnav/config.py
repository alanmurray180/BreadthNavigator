from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "pairs.yaml"


@dataclass(frozen=True)
class Pair:
    id: str
    name: str
    cap: str
    equal: str
    notes: str = ""
    providers: tuple[str, ...] = ()  # empty = all providers
    optional: bool = False  # a missing optional pair warns instead of failing the build
    duplicate_of: str = ""  # same index as another pair; left out of cross-index counts

    @property
    def symbols(self) -> list[str]:
        return [self.cap, self.equal]

    def supported_by(self, provider: str) -> bool:
        return not self.providers or provider in self.providers


@dataclass(frozen=True)
class Settings:
    provider: str = "yahoo"
    refresh_seconds: int = 60
    intraday_interval: str = "1m"
    history_start: str = "2018-01-01"
    rolling_window: int = 21
    zscore_lookback: int = 252


@dataclass(frozen=True)
class Config:
    settings: Settings
    pairs: tuple[Pair, ...] = field(default_factory=tuple)

    def pair(self, pair_id: str) -> Pair:
        for p in self.pairs:
            if p.id == pair_id:
                return p
        raise KeyError(pair_id)

    def pairs_for(self, provider: str) -> list[Pair]:
        return [p for p in self.pairs if p.supported_by(provider)]


def load_config(path: str | os.PathLike | None = None) -> Config:
    path = Path(path or os.environ.get("BREADTHNAV_CONFIG", DEFAULT_CONFIG))
    raw = yaml.safe_load(path.read_text()) or {}
    s = dict(raw.get("settings") or {})
    if os.environ.get("BREADTHNAV_PROVIDER"):
        s["provider"] = os.environ["BREADTHNAV_PROVIDER"]
    if "history_start" in s:
        s["history_start"] = str(s["history_start"])
    settings = Settings(**s)

    pairs, seen = [], set()
    for p in raw.get("pairs") or []:
        p = dict(p)
        p["providers"] = tuple(p.get("providers") or ())
        pair = Pair(**p)
        if pair.id in seen:
            raise ValueError(f"duplicate pair id: {pair.id}")
        seen.add(pair.id)
        pairs.append(pair)
    return Config(settings=settings, pairs=tuple(pairs))
