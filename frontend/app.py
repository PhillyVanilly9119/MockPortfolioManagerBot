"""
MockPortfolioManagerBot — Streamlit Dashboard
Connects to the FastAPI backend (API_BASE env var) and renders:
  • Summary metric cards
  • Normalised performance chart (Portfolio vs S&P 500)
  • Current holdings table
  • Decision log (ticker | action | reasoning TL;DR)
"""

import os
import time

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE: str = os.environ.get("API_BASE", "http://localhost:8000")
REFRESH_INTERVAL_SECS: int = 30

st.set_page_config(
    page_title="MockPortfolioManagerBot",
    page_icon="📈",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("📈 MockPortfolioManagerBot")
    st.caption("Paper-trading S&P 500 · Powered by yfinance + Ollama")

    auto_refresh = st.checkbox("Auto-refresh every 30 s", value=False)
    manual_refresh = st.button("🔄 Refresh Now")
    st.divider()

    st.subheader("Quick Actions")
    if st.button("⚡ Trigger Trading Cycle", use_container_width=True):
        try:
            r = requests.post(f"{API_BASE}/trigger", timeout=5)
            if r.ok:
                st.success("Cycle triggered — data will refresh shortly.")
            else:
                st.error(f"Error: {r.status_code}")
        except requests.RequestException as exc:
            st.error(f"Backend unreachable: {exc}")

    st.divider()
    st.caption(f"Backend: `{API_BASE}`")


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


@st.cache_data(ttl=REFRESH_INTERVAL_SECS)
def fetch(endpoint: str, params: dict | None = None):
    try:
        r = requests.get(f"{API_BASE}{endpoint}", params=params, timeout=8)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


if manual_refresh:
    st.cache_data.clear()

if auto_refresh:
    time.sleep(REFRESH_INTERVAL_SECS)
    st.rerun()

portfolio = fetch("/portfolio")
benchmark = fetch("/benchmark")
snapshots = fetch("/snapshots", {"limit": 500})
trades = fetch("/trades", {"limit": 100})

# ---------------------------------------------------------------------------
# Header — metric cards
# ---------------------------------------------------------------------------

st.header("Portfolio Overview", divider="gray")

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    total = portfolio["total_value"] if portfolio else 0.0
    initial = benchmark["initial_cash"] if benchmark else 100_000.0
    delta_pct = ((total - initial) / initial * 100) if initial else 0.0
    st.metric(
        "Total Value",
        f"${total:,.2f}",
        delta=f"{delta_pct:+.2f}% vs start",
    )

with col2:
    st.metric("Cash", f"${portfolio['cash']:,.2f}" if portfolio else "—")

with col3:
    st.metric(
        "Holdings Value",
        f"${portfolio['holdings_value']:,.2f}" if portfolio else "—",
    )

with col4:
    sp = benchmark["sp500_price"] if benchmark else 0.0
    st.metric("S&P 500 (^GSPC)", f"${sp:,.2f}" if sp else "—")

with col5:
    n_positions = len(portfolio["positions"]) if portfolio else 0
    st.metric("Open Positions", n_positions)

st.divider()

# ---------------------------------------------------------------------------
# Performance chart — Portfolio vs S&P 500 (both normalised to 100)
# ---------------------------------------------------------------------------

st.subheader("Performance vs S&P 500 Benchmark")

if snapshots and len(snapshots) >= 2:
    df = pd.DataFrame(snapshots)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    start_p = df["total_value"].iloc[0]
    start_s = df["sp500_value"].iloc[0]

    if start_p > 0 and start_s > 0:
        df["portfolio_norm"] = (df["total_value"] / start_p) * 100
        df["sp500_norm"] = (df["sp500_value"] / start_s) * 100

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=df["portfolio_norm"],
                name="Portfolio",
                line=dict(color="#00d4aa", width=2.5),
                hovertemplate="<b>Portfolio</b><br>%{x}<br>%{y:.1f}<extra></extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=df["sp500_norm"],
                name="S&P 500",
                line=dict(color="#ff6b6b", width=2, dash="dot"),
                hovertemplate="<b>S&P 500</b><br>%{x}<br>%{y:.1f}<extra></extra>",
            )
        )
        fig.update_layout(
            template="plotly_dark",
            height=380,
            margin=dict(l=40, r=20, t=20, b=40),
            yaxis_title="Normalised Value (base = 100)",
            xaxis_title=None,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info(
        "Waiting for at least 2 portfolio snapshots. "
        "The first snapshot is recorded at the end of each trading cycle."
    )

st.divider()

# ---------------------------------------------------------------------------
# Current Holdings table
# ---------------------------------------------------------------------------

st.subheader("Current Holdings")

if portfolio and portfolio.get("positions"):
    pos_df = pd.DataFrame(portfolio["positions"])
    pos_df = pos_df.rename(
        columns={
            "ticker": "Ticker",
            "shares": "Shares",
            "avg_price": "Avg Cost ($)",
            "current_price": "Price ($)",
            "market_value": "Market Value ($)",
            "pnl_pct": "P&L %",
        }
    )

    # Colour P&L column
    def _pnl_colour(val):
        if isinstance(val, (int, float)):
            if val > 0:
                return "color: #00d4aa; font-weight: bold"
            if val < 0:
                return "color: #ff6b6b; font-weight: bold"
        return ""

    styled = pos_df.style.map(_pnl_colour, subset=["P&L %"])
    st.dataframe(styled, use_container_width=True, hide_index=True)
else:
    st.info("No open positions — waiting for the first BUY signal.")

st.divider()

# ---------------------------------------------------------------------------
# Decision Log
# ---------------------------------------------------------------------------

st.subheader("Decision Log")

if trades:
    log_df = pd.DataFrame(trades)
    log_df["timestamp"] = pd.to_datetime(log_df["timestamp"]).dt.strftime(
        "%Y-%m-%d %H:%M"
    )
    log_df = log_df[
        ["timestamp", "ticker", "action", "shares", "price", "total_value", "reasoning"]
    ]
    log_df.columns = [
        "Time", "Ticker", "Action", "Shares", "Price ($)", "Total ($)", "Reasoning TL;DR"
    ]

    def _action_colour(val):
        if val == "BUY":
            return "color: #00d4aa; font-weight: bold"
        if val == "SELL":
            return "color: #ff6b6b; font-weight: bold"
        return ""

    styled_log = log_df.style.map(_action_colour, subset=["Action"])
    st.dataframe(styled_log, use_container_width=True, hide_index=True, height=420)
else:
    st.info("No trades recorded yet.")
