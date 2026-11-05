"""CLI snapshot:  python -m breadthnav [--provider yahoo] [--csv log.csv]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from .config import load_config
from .data import fetch, with_live_bar
from .metrics import snapshot
from .providers import get_provider


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="breadthnav")
    ap.add_argument("--config")
    ap.add_argument("--provider")
    ap.add_argument("--csv", help="append the snapshot rows to this CSV")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    s = cfg.settings
    provider_name = args.provider or s.provider
    pairs = cfg.pairs_for(provider_name)
    md = fetch(get_provider(provider_name), pairs, s.history_start, s.intraday_interval)

    daily = with_live_bar(md.daily, md.intraday)
    rows = [snapshot(p, daily, md.intraday, s.rolling_window, s.zscore_lookback)
            for p in pairs if md.has(p)]
    df = pd.DataFrame(rows)
    for k, v in md.errors.items():
        print(f"warning [{k}]: {v}", file=sys.stderr)
    if df.empty:
        return 1

    pct = [c for c in df.columns if c.startswith(("today_", "spread_", "roll_"))]
    view = df.copy()
    view[pct] = view[pct].map(lambda x: f"{x * 100:+.2f}%" if pd.notna(x) else "")
    view["zscore"] = view["zscore"].map(lambda x: f"{x:+.2f}" if pd.notna(x) else "")
    view["ratio_pctile"] = view["ratio_pctile"].map(lambda x: f"{x:.0f}")
    print(view.to_string(index=False))

    if args.csv:
        path = Path(args.csv)
        df.assign(fetched_at=pd.Timestamp.now(tz="UTC")).to_csv(
            path, mode="a", header=not path.exists(), index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
