"""Pages build: allow-list, rendering, and Python <-> JavaScript metric parity."""
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from breadthnav import metrics as m
from breadthnav.config import Pair, load_config
from breadthnav.data import unique_symbols, with_live_bar
from breadthnav.providers.base import frame_from_series

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_static  # noqa: E402

NODE = shutil.which("node")
PAIR = Pair(id="t", name="Test", cap="CAP", equal="EQ")


def test_config_symbols_are_allowed_by_worker():
    toml = tomllib.loads((ROOT / "worker" / "wrangler.toml").read_text())
    allowed = set(toml["vars"]["SYMBOLS"].split(","))
    assert set(toml["previews"]["vars"]["SYMBOLS"].split(",")) == allowed
    cfg = load_config()
    missing = set(unique_symbols(list(cfg.pairs))) - allowed
    assert not missing, f"add {sorted(missing)} to SYMBOLS in worker/wrangler.toml"


def synthetic_daily(n=900, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize() - pd.offsets.BDay(1), periods=n)
    cap = np.round(100 * np.cumprod(1 + rng.normal(0.0005, 0.012, n)), 4)
    eq = np.round(50 * np.cumprod(1 + rng.normal(0.0003, 0.011, n)), 4)
    eq[:40] = np.nan  # equal leg incepts later
    raw_cap = np.round(cap * 1.01, 4)
    raw_eq = np.round(eq * 1.02, 4)
    return frame_from_series({
        ("close", "CAP"): pd.Series(raw_cap, idx), ("adj_close", "CAP"): pd.Series(cap, idx),
        ("close", "EQ"): pd.Series(raw_eq, idx), ("adj_close", "EQ"): pd.Series(eq, idx),
    })


def live_fixture(daily):
    """1-minute bars for the next session, with gaps in the thin leg."""
    session = daily.index[-1] + pd.offsets.BDay(1)
    ts = pd.date_range(session + pd.Timedelta("9h30min"), periods=30, freq="min", tz="America/New_York")
    rng = np.random.default_rng(9)
    cap = np.round(daily[("close", "CAP")].iloc[-1] * np.cumprod(1 + rng.normal(0, 0.0006, 30)), 4)
    eq = np.round(daily[("close", "EQ")].iloc[-1] * np.cumprod(1 + rng.normal(0, 0.0006, 30)), 4)
    eq_bars = [(t, v) for i, (t, v) in enumerate(zip(ts, eq)) if i % 3 != 1]
    intraday = pd.DataFrame({"CAP": pd.Series(cap, ts), "EQ": pd.Series(dict(eq_bars))})
    sess = session.strftime("%Y-%m-%d")
    quotes = {
        "CAP": {"price": float(cap[-1]), "prevClose": None, "time": int(ts[-1].timestamp()),
                "session": sess, "bars": {"t": [int(t.timestamp()) for t in ts], "c": cap.tolist()}},
        "EQ": {"price": float(eq_bars[-1][1]), "prevClose": None, "time": int(eq_bars[-1][0].timestamp()),
               "session": sess, "bars": {"t": [int(t.timestamp()) for t, _ in eq_bars],
                                         "c": [float(v) for _, v in eq_bars]}},
    }
    return intraday, quotes


def run_js(hist, quotes, window=21, lookback=252):
    script = f"""
const BN = require({json.dumps(str(ROOT / 'site' / 'metrics.js'))});
const inp = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const pair = {{id: 't', cap: 'CAP', equal: 'EQ'}};
const p = BN.withLive(BN.pairPrices(inp.hist, pair), pair, inp.quotes);
const out = {{
  snap: BN.snapshot(inp.hist, pair, inp.quotes, {window}, {lookback}),
  periods: BN.periodReturns(p),
  intra: BN.intradaySpread(inp.hist, pair, inp.quotes),
}};
process.stdout.write(JSON.stringify(out, (k, v) => (typeof v === 'number' && !isFinite(v)) ? null : v));
"""
    r = subprocess.run([NODE, "-e", script], input=json.dumps({"hist": hist, "quotes": quotes}),
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def close(a, b, tol=1e-9):
    if a is None or (isinstance(a, float) and np.isnan(a)):
        return b is None or (isinstance(b, float) and np.isnan(b))
    return b is not None and abs(a - b) <= tol * max(1, abs(a))


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("with_live", [False, True])
def test_js_matches_python(with_live):
    daily = synthetic_daily()
    hist = build_static.history_payload(daily, ["CAP", "EQ"])
    intraday, quotes = live_fixture(daily) if with_live else (None, {})
    js = run_js(hist, quotes)

    d = with_live_bar(daily, intraday)
    py = m.snapshot(PAIR, d, intraday, 21, 252)
    for k in ("today_cap", "today_equal", "today_spread", "spread_1M", "spread_YTD",
              "spread_1Y", "zscore", "ratio_pctile"):
        assert close(py[k], js["snap"][k]), (k, py[k], js["snap"][k])
    assert close(py["roll_21d"], js["snap"]["roll"])

    pr = m.period_returns(m.pair_prices(d, PAIR))
    for per in m.PERIODS:
        for f in ("cap", "equal", "spread"):
            assert close(pr.loc[per, f], js["periods"][per][f]), (per, f)

    if with_live:
        intra = m.intraday_spread(intraday, d, PAIR)
        assert len(intra) == len(js["intra"]["spread"])
        assert np.allclose(intra["spread"].to_numpy(), js["intra"]["spread"], atol=1e-12)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_js_month_offsets_match_pandas():
    dates = ["2024-03-31", "2024-05-31", "2025-02-28", "2024-02-29", "2026-01-15"]
    script = (f"const BN=require({json.dumps(str(ROOT / 'site' / 'metrics.js'))});"
              f"console.log(JSON.stringify({json.dumps(dates)}.map(d=>[1,3,6,12,36].map(n=>BN.subMonths(d,n)))))")
    js = json.loads(subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True).stdout)
    for d, row in zip(dates, js):
        exp = [(pd.Timestamp(d) - pd.DateOffset(months=n)).strftime("%Y-%m-%d") for n in (1, 3, 6, 12, 36)]
        assert row == exp, d


def test_build_payload_and_render(monkeypatch):
    monkeypatch.setenv("LIVE_URL", "https://example.workers.dev/live")
    cfg = load_config()
    daily = synthetic_daily()
    # rename synthetic legs onto every configured symbol
    frames = {}
    for s in unique_symbols(cfg.pairs_for("yahoo")):
        src = "CAP" if len(frames) % 4 < 2 else "EQ"
        for f in ("close", "adj_close"):
            frames[(f, s)] = daily[(f, src)]
    full = frame_from_series(frames)
    data, fatal = build_static.build_payload(cfg, full, {"quotes": {}, "errors": []}, "yahoo")
    assert not fatal and len(data["pairs"]) == len(cfg.pairs_for("yahoo"))
    assert data["live_url"].endswith("/live")
    html = build_static.render(data)
    assert "/*__DATA__*/" not in html and "/*__METRICS__*/" not in html
    assert "const BN" in html and '"ndx100"' in html


def test_build_blocks_on_missing_required_pair_but_not_optional():
    cfg = load_config()
    daily = synthetic_daily()
    frames = {(f, s): daily[(f, "CAP")] for f in ("close", "adj_close")
              for s in unique_symbols(cfg.pairs_for("yahoo")) if s not in ("^NDXE", "EDOW")}
    data, fatal = build_static.build_payload(cfg, frame_from_series(frames), None, "yahoo")
    assert any("Dow" in f for f in fatal)
    assert not any("index level" in f for f in fatal)  # optional pair only warns
    assert all(p["id"] not in ("djia", "ndx100_index") for p in data["pairs"])


def test_build_blocks_on_stale_history():
    cfg = load_config()
    daily = synthetic_daily().iloc[:-20]
    frames = {(f, s): daily[(f, "CAP")] for f in ("close", "adj_close")
              for s in unique_symbols(cfg.pairs_for("yahoo"))}
    _, fatal = build_static.build_payload(cfg, frame_from_series(frames), None, "yahoo")
    assert any("business days ago" in f for f in fatal)


@pytest.mark.parametrize("url,ok", [
    ("https://breadthnavigator.alan-ae0.workers.dev/live", True),
    ("https://breadthnavigator.alan-ae0.workers.dev/live/", True),
    ("https//:breadthnavigator.alan-ae0.workers.dev/live", False),  # the real typo, Nov 2026
    ("http://breadthnavigator.alan-ae0.workers.dev/live", False),
    ("breadthnavigator.alan-ae0.workers.dev/live", False),
    ("https://breadthnavigator.alan-ae0.workers.dev/", False),
])
def test_live_url_validation(url, ok, monkeypatch):
    assert (build_static.check_live_url(url) is None) == ok
    monkeypatch.setenv("LIVE_URL", url)
    cfg = load_config()
    daily = synthetic_daily()
    frames = {(f, s): daily[(f, "CAP")] for f in ("close", "adj_close")
              for s in unique_symbols(cfg.pairs_for("yahoo"))}
    data, fatal = build_static.build_payload(cfg, frame_from_series(frames), None, "yahoo")
    assert not fatal
    assert ("live_url" in data) == ok and ("live_url_error" in data) == (not ok)
