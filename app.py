"""BreadthNavigator dashboard:  streamlit run app.py"""
from __future__ import annotations

from datetime import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from breadthnav import metrics as m
from breadthnav.config import load_config
from breadthnav.data import MarketData, unique_symbols, with_live_bar
from breadthnav.providers import available, get_provider

CAP_C, EQ_C, SPREAD_C = "#2a78d6", "#eb6834", "#6250d6"
NY, UK = "America/New_York", "Europe/London"
LOOKBACKS = {"6M": pd.DateOffset(months=6), "1Y": pd.DateOffset(years=1),
             "3Y": pd.DateOffset(years=3), "5Y": pd.DateOffset(years=5), "Max": None}

st.set_page_config(page_title="BreadthNavigator", layout="wide")
cfg = load_config()
S = cfg.settings


# ---------- data (cached) ----------
@st.cache_data(ttl=1800, show_spinner="Loading daily history...")
def load_daily(provider: str, symbols: tuple[str, ...], start: str) -> pd.DataFrame:
    return get_provider(provider).daily(list(symbols), start)


@st.cache_data(ttl=max(S.refresh_seconds - 5, 10), show_spinner=False)
def load_intraday(provider: str, symbols: tuple[str, ...], interval: str) -> pd.DataFrame:
    return get_provider(provider).intraday(list(symbols), interval)


def market_open(now: pd.Timestamp) -> bool:
    ny = now.tz_convert(NY)
    return ny.weekday() < 5 and time(9, 30) <= ny.time() <= time(16, 5)  # ignores holidays


# ---------- formatting ----------
def pct(x, dp=2):
    return "–" if pd.isna(x) else f"{x * 100:+.{dp}f}%"


def bp(x):
    return "–" if pd.isna(x) else f"{x * 1e4:+.0f} bp"


def base_fig(title: str, yfmt: str = ".1%") -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        title=dict(text=title, x=0, font=dict(size=14)), height=320,
        margin=dict(l=10, r=10, t=40, b=10), hovermode="x unified",
        legend=dict(orientation="h", y=1.12, x=1, xanchor="right"),
        yaxis=dict(tickformat=yfmt, gridcolor="rgba(128,128,128,0.15)", zeroline=False),
        xaxis=dict(showgrid=False),
    )
    return fig


def line(fig, x, y, name, color, fmt=".2%"):
    fig.add_trace(go.Scatter(x=x, y=y, name=name, mode="lines",
                             line=dict(color=color, width=2),
                             hovertemplate=f"%{{y:{fmt}}}<extra>{name}</extra>"))


def zero(fig):
    fig.add_hline(y=0, line=dict(color="rgba(128,128,128,0.6)", width=1))


# ---------- sidebar ----------
with st.sidebar:
    st.header("BreadthNavigator")
    provider = st.selectbox("Data source", available(), index=available().index(S.provider))
    pairs = cfg.pairs_for(provider)
    detail = st.selectbox("Detail index", [p.name for p in pairs])
    live = st.toggle("Auto-refresh in market hours", value=True)
    st.caption(f"Refresh every {S.refresh_seconds}s · {S.intraday_interval} bars")
    if st.button("Refresh now"):
        st.cache_data.clear()
    st.divider()
    st.caption("Spread = cap-weighted return − equal-weighted return.  \n"
               "**> 0** mega-caps leading (narrowing breadth)  \n"
               "**< 0** average stock leading (broadening)")

symbols = tuple(unique_symbols(pairs))
try:
    daily_raw = load_daily(provider, symbols, S.history_start)
except Exception as exc:
    st.error(f"Daily history from **{provider}** failed: {exc}")
    st.stop()

now = pd.Timestamp.now(tz="UTC")
run_every = S.refresh_seconds if (live and market_open(now)) else None


@st.fragment(run_every=run_every)
def live_view():
    errors = {}
    try:
        intraday = load_intraday(provider, symbols, S.intraday_interval)
    except Exception as exc:
        intraday, errors["intraday"] = None, str(exc)
    md = MarketData(daily=with_live_bar(daily_raw, intraday), intraday=intraday, errors=errors)
    ok = [p for p in pairs if md.has(p)]
    for p in pairs:
        if p not in ok:
            md.errors[p.id] = f"no price history for {p.cap} / {p.equal} from {provider}"

    stamp = pd.Timestamp.now(tz="UTC")
    bar_ts = intraday.index[-1] if intraday is not None and not intraday.empty else None
    status = "🟢 market open" if market_open(stamp) else "⚪ market closed"
    st.caption(
        f"{status} · fetched {stamp.tz_convert(UK):%H:%M:%S} UK / {stamp.tz_convert(NY):%H:%M:%S} ET"
        + (f" · last bar {bar_ts:%a %d %b %H:%M} ET" if bar_ts is not None else ""))
    for k, v in md.errors.items():
        st.warning(f"{k}: {v}")
    if not ok:
        st.stop()

    # ----- overview across every configured index -----
    rows = [m.snapshot(p, md.daily, intraday, S.rolling_window, S.zscore_lookback) for p in ok]
    ov = pd.DataFrame(rows)
    ov.index = ov["pair"] + " · " + ov["cap"] + "/" + ov["equal"]
    ov = ov.drop(columns=["pair", "cap", "equal"])
    pcols = ["today_cap", "today_equal", "today_spread", "spread_1M", "spread_YTD",
             "spread_1Y", f"roll_{S.rolling_window}d"]
    ov[pcols] = ov[pcols] * 100
    st.subheader("All indices")
    st.dataframe(
        ov.drop(columns=["as_of"]), width="stretch",
        column_config={
            "today_cap": st.column_config.NumberColumn("Today cap", format="%+.2f%%"),
            "today_equal": st.column_config.NumberColumn("Today equal", format="%+.2f%%"),
            "today_spread": st.column_config.NumberColumn("Today spread", format="%+.2f%%"),
            "spread_1M": st.column_config.NumberColumn("1M spread", format="%+.2f%%"),
            "spread_YTD": st.column_config.NumberColumn("YTD spread", format="%+.2f%%"),
            "spread_1Y": st.column_config.NumberColumn("1Y spread", format="%+.2f%%"),
            f"roll_{S.rolling_window}d": st.column_config.NumberColumn(
                f"{S.rolling_window}d spread", format="%+.2f%%"),
            "zscore": st.column_config.NumberColumn(
                "Z-score", format="%+.2f",
                help=f"{S.rolling_window}d spread vs trailing {S.zscore_lookback}d distribution"),
            "ratio_pctile": st.column_config.ProgressColumn(
                "Ratio pctile", format="%.0f", min_value=0, max_value=100,
                help="Cap/equal ratio vs its own history (100 = most concentrated ever)"),
        },
    )

    # ----- single-pair detail -----
    st.divider()
    pair = next((p for p in ok if p.name == detail), ok[0])
    st.subheader(pair.name)
    prices = m.pair_prices(md.daily, pair)
    pr = m.period_returns(prices)
    roll = m.rolling_spread(prices, S.rolling_window)
    z = m.zscore(roll, S.zscore_lookback)
    intra = m.intraday_spread(intraday, md.daily, pair) if intraday is not None else pd.DataFrame()

    k = st.columns(5)
    if not intra.empty:
        last = intra.iloc[-1]
        k[0].metric(f"{pair.cap} today", pct(last["cap"]))
        k[1].metric(f"{pair.equal} today", pct(last["equal"]))
        k[2].metric("Spread today", bp(last["spread"]))
    k[3].metric(f"{S.rolling_window}d spread", pct(roll.iloc[-1]),
                help="cap − equal, trailing window")
    k[4].metric("Z-score", "–" if pd.isna(z.iloc[-1]) else f"{z.iloc[-1]:+.2f}")
    if pair.notes:
        st.caption(pair.notes)

    left, right = st.columns(2)
    with left:
        if not intra.empty:
            f = base_fig("Intraday · % vs prior close", ".2%")
            line(f, intra.index, intra["cap"], pair.cap, CAP_C)
            line(f, intra.index, intra["equal"], pair.equal, EQ_C)
            zero(f)
            st.plotly_chart(f, width="stretch", theme="streamlit")
        else:
            st.info("No intraday bars available.")
    with right:
        if not intra.empty:
            f = base_fig("Intraday spread (cap − equal)", ".2%")
            line(f, intra.index, intra["spread"], "Spread", SPREAD_C)
            zero(f)
            f.update_layout(showlegend=False)
            st.plotly_chart(f, width="stretch", theme="streamlit")

    st.markdown("**Period returns** (total return)")
    tbl = (pr * 100).rename(columns={"cap": pair.cap, "equal": pair.equal, "spread": "Spread"}).T
    st.dataframe(tbl.style.format("{:+.2f}%", na_rep="–"), width="stretch")
    return pair, prices, roll, z


result = live_view()

# ----- history (outside the fragment: only redraws on interaction / daily refresh) -----
if result:
    pair, prices, roll, z = result
    st.divider()
    lb = st.segmented_control("History", list(LOOKBACKS), default="3Y", key="lb") or "3Y"
    off = LOOKBACKS[lb]
    start = prices.index[-1] - off if off is not None else prices.index[0]
    start = max(start, prices.index[0])

    left, right = st.columns(2)
    with left:
        rb = m.rebased(prices, start) / 100 - 1
        f = base_fig(f"Cumulative total return since {start:%d %b %Y}", ".0%")
        line(f, rb.index, rb["cap"], pair.cap, CAP_C, ".1%")
        line(f, rb.index, rb["equal"], pair.equal, EQ_C, ".1%")
        zero(f)
        st.plotly_chart(f, width="stretch", theme="streamlit")
    with right:
        ratio = m.relative_ratio(prices, start)
        f = base_fig(f"Relative ratio {pair.cap}/{pair.equal} (rebased 100; rising = concentration)", ".0f")
        line(f, ratio.index, ratio, "Ratio", SPREAD_C, ".1f")
        f.add_hline(y=100, line=dict(color="rgba(128,128,128,0.6)", width=1))
        f.update_layout(showlegend=False)
        st.plotly_chart(f, width="stretch", theme="streamlit")

    r = roll[roll.index >= start]
    f = base_fig(f"Rolling {S.rolling_window}-day spread (cap − equal)", ".1%")
    line(f, r.index, r, "Spread", SPREAD_C)
    zero(f)
    f.update_layout(showlegend=False)
    st.plotly_chart(f, width="stretch", theme="streamlit")
    st.caption("Cumulative figures include the fee differential between the two ETFs "
               "(e.g. QQQM 0.15% vs QQQE 0.35% ≈ 20 bp/yr in the cap leg's favour).")
