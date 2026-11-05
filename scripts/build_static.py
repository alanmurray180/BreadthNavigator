#!/usr/bin/env python3
"""Build the GitHub Pages dashboard: dist/index.html, one self-contained file.

  python scripts/build_static.py [dist] [--live live.json]

Daily history comes from the configured provider (Yahoo by default) and is baked in;
the page then polls the Worker's GET /live (LIVE_URL) for intraday bars and recomputes
in the browser with site/metrics.js. live.json is the build-time snapshot of that feed
(worker/snapshot.mjs), shown when the Worker cannot answer.

Fails loudly - exit non-zero, so the deploy is skipped and Pages keeps the previous
version - when a required pair has no history or the history is stale.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from breadthnav.config import load_config  # noqa: E402
from breadthnav.data import unique_symbols  # noqa: E402
from breadthnav.providers import get_provider  # noqa: E402

STALE_BDAYS = 4  # more business days than this since the last close fails the build


def annotate(level: str, title: str, msg: str) -> None:
    print(f"{level}: {title}: {msg}", file=sys.stderr)
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::{level} title={title}::{msg}")


def _num(x, dp=4):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), dp)


def history_payload(daily: pd.DataFrame, symbols: list[str]) -> dict:
    daily = daily.sort_index()
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in daily.index],
        "adj": {s: [_num(v) for v in daily[("adj_close", s)]] for s in symbols},
        "close": {s: [_num(v) for v in daily[("close", s)]] for s in symbols},
    }


def build_payload(cfg, daily: pd.DataFrame, live: dict | None, provider: str) -> tuple[dict, list[str]]:
    """Return (page data, fatal errors)."""
    fatal, pairs = [], []
    for p in cfg.pairs_for(provider):
        ok = all(("adj_close", s) in daily.columns and daily[("adj_close", s)].notna().sum() > 1
                 for s in p.symbols)
        if ok:
            pairs.append(p)
        elif p.optional:
            annotate("warning", "Pair dropped", f"{p.name}: no history for {p.cap}/{p.equal}")
        else:
            fatal.append(f"{p.name}: no history for {p.cap}/{p.equal}")

    symbols = unique_symbols(pairs)
    if pairs:
        last = daily[[("adj_close", s) for s in symbols]].dropna(how="all").index.max()
        lag = len(pd.bdate_range(last, pd.Timestamp.now(tz="UTC").tz_localize(None).normalize())) - 1
        if lag > STALE_BDAYS:
            fatal.append(f"history ends {last.date()}, {lag} business days ago")

    s = cfg.settings
    data = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": provider,
        "settings": {"rolling_window": s.rolling_window, "zscore_lookback": s.zscore_lookback,
                     "poll_seconds": s.refresh_seconds},
        "pairs": [{"id": p.id, "name": p.name, "cap": p.cap, "equal": p.equal, "notes": p.notes}
                  for p in pairs],
        "history": history_payload(daily, symbols) if pairs else {"dates": [], "adj": {}, "close": {}},
        "live": live,
    }
    live_url = os.environ.get("LIVE_URL", "").strip()
    if live_url:
        data["live_url"] = live_url
    return data, fatal


def render(data: dict) -> str:
    tpl = (ROOT / "site" / "template.html").read_text(encoding="utf-8")
    js = (ROOT / "site" / "metrics.js").read_text(encoding="utf-8")
    for ph in ("/*__DATA__*/", "/*__METRICS__*/"):
        assert ph in tpl, f"placeholder {ph} missing from template"
    blob = json.dumps(data, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    return tpl.replace("/*__METRICS__*/", js).replace("/*__DATA__*/", blob)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="dist")
    ap.add_argument("--live", default="live.json", help="build-time snapshot from worker/snapshot.mjs")
    ap.add_argument("--symbols-only", action="store_true",
                    help="print the comma-separated symbol list and exit (for snapshot.mjs)")
    args = ap.parse_args(argv)

    cfg = load_config()
    provider = cfg.settings.provider
    pairs = cfg.pairs_for(provider)
    symbols = unique_symbols(pairs)
    if args.symbols_only:
        print(",".join(symbols))
        return 0

    daily = get_provider(provider).daily(symbols, cfg.settings.history_start)

    live = None
    lp = Path(args.live)
    if lp.exists():
        try:
            live = json.loads(lp.read_text())
        except ValueError as e:
            annotate("warning", "live.json unreadable", str(e))

    data, fatal = build_payload(cfg, daily, live, provider)
    for f in fatal:
        annotate("error", "Build blocked", f)
    if fatal:
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    html = render(data)
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("")
    print(f"wrote {out / 'index.html'}  {len(html) / 1e6:.2f} MB, {len(data['pairs'])} pairs, "
          f"{len(data['history']['dates'])} sessions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
