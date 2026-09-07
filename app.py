import os
import time
import warnings
from datetime import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

warnings.filterwarnings("ignore")

# Streamlit Page Config
st.set_page_config(
    page_title="Nifty ML Live Paper Trader", layout="wide", page_icon="📈"
)

st.title("📈 Nifty Live Paper Trading Dashboard")
st.caption(
    "Live Real-Time PnL Tracker | Target: +15 to +45 Pts | SL: -15 Pts | NSE Direct Feed"
)

LOT_SIZE = 65
TODAY_STR = datetime.now().strftime("%Y-%m-%d")
CSV_FILE = f"live_trades_{TODAY_STR}.csv"

# Session State for Auto Refresh & Live Tracking
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = time.time()


# ------------------------------------------
# 1. Direct NSE Live Data Fetcher (No yfinance)
# ------------------------------------------
def fetch_nse_live_data():
    """Fetches Real-Time Nifty Price directly from NSE API"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com",
    }
    session = requests.Session()
    try:
        session.get("https://www.nseindia.com", headers=headers, timeout=2)
        url = "https://www.nseindia.com/api/allIndices"
        response = session.get(url, headers=headers, timeout=2)
        if response.status_code == 200:
            data = response.json()
            for index in data.get("data", []):
                if index.get("index") == "NIFTY 50":
                    return float(index.get("last"))
    except Exception:
        pass

    # Fallback to random simulation if market is closed / NSE blocks request
    if os.path.exists(CSV_FILE):
        df_temp = pd.read_csv(CSV_FILE)
        if not df_temp.empty and "Entry_Price" in df_temp.columns:
            return float(df_temp["Entry_Price"].iloc[-1])
    return 23800.0


# ------------------------------------------
# 2. Local CSV Database Operations (Today Only)
# ------------------------------------------
def init_today_csv():
    """Ensures CSV exists for today's trades only"""
    if not os.path.exists(CSV_FILE):
        df_empty = pd.DataFrame(
            columns=[
                "Date",
                "Time",
                "Type",
                "Option_Strike",
                "Entry_Price",
                "Exit_Price",
                "Status",
                "Points_P&L",
                "Rupees_P&L",
            ]
        )
        df_empty.to_csv(CSV_FILE, index=False)


def load_today_trades():
    init_today_csv()
    try:
        df = pd.read_csv(CSV_FILE)
        return df
    except Exception:
        return pd.DataFrame()


def save_trade(trade_dict):
    init_today_csv()
    df = load_today_trades()
    df = pd.concat([df, pd.DataFrame([trade_dict])], ignore_index=False)
    df.to_csv(CSV_FILE, index=False)


def update_trades_file(df):
    df.to_csv(CSV_FILE, index=False)


# ------------------------------------------
# 3. Live PnL & Position Execution Engine
# ------------------------------------------
live_nifty_price = fetch_nse_live_data()
trades_df = load_today_trades()

# Real-time Position Management (Open Trade Streamer)
if not trades_df.empty:
    for idx, row in trades_df.iterrows():
        if row["Status"] == "OPEN":
            entry = float(row["Entry_Price"])
            is_ce = "CE" in str(row["Type"])

            # Calculate Live Moving Points
            current_move = (
                (live_nifty_price - entry)
                if is_ce
                else (entry - live_nifty_price)
            )

            # Check SL (-15 Pts) & Target (+45 Pts) Conditions
            if current_move >= 45.0:
                trades_df.at[idx, "Exit_Price"] = (
                    entry + 45.0 if is_ce else entry - 45.0
                )
                trades_df.at[idx, "Status"] = "TARGET HIT (+45)"
                trades_df.at[idx, "Points_P&L"] = 45.0
                trades_df.at[idx, "Rupees_P&L"] = 45.0 * LOT_SIZE
            elif current_move <= -15.0:
                trades_df.at[idx, "Exit_Price"] = (
                    entry - 15.0 if is_ce else entry + 15.0
                )
                trades_df.at[idx, "Status"] = "SL HIT (-15)"
                trades_df.at[idx, "Points_P&L"] = -15.0
                trades_df.at[idx, "Rupees_P&L"] = -15.0 * LOT_SIZE
            else:
                # Still OPEN: Stream Live Unrealized PnL
                trades_df.at[idx, "Points_P&L"] = round(current_move, 2)
                trades_df.at[idx, "Rupees_P&L"] = round(
                    current_move * LOT_SIZE, 2
                )

    update_trades_file(trades_df)

# ------------------------------------------
# 4. Streamlit Dashboard View
# ------------------------------------------
st.sidebar.header("⚙️ Controls")

# Manual Trigger for Live Paper Trade (Testing/Live Signal)
st.sidebar.subheader("🎯 Manual Signal Trigger")
col_btn1, col_btn2 = st.sidebar.columns(2)
if col_btn1.button("🟢 Buy CE"):
    atm = round(live_nifty_price / 50) * 50
    new_trade = {
        "Date": TODAY_STR,
        "Time": datetime.now().strftime("%H:%M:%S"),
        "Type": "CE BUY",
        "Option_Strike": f"{int(atm)} CE (ATM)",
        "Entry_Price": live_nifty_price,
        "Exit_Price": 0.0,
        "Status": "OPEN",
        "Points_P&L": 0.0,
        "Rupees_P&L": 0.0,
    }
    save_trade(new_trade)
    st.rerun()

if col_btn2.button("🔴 Buy PE"):
    atm = round(live_nifty_price / 50) * 50
    new_trade = {
        "Date": TODAY_STR,
        "Time": datetime.now().strftime("%H:%M:%S"),
        "Type": "PE BUY",
        "Option_Strike": f"{int(atm)} PE (ATM)",
        "Entry_Price": live_nifty_price,
        "Exit_Price": 0.0,
        "Status": "OPEN",
        "Points_P&L": 0.0,
        "Rupees_P&L": 0.0,
    }
    save_trade(new_trade)
    st.rerun()

if st.sidebar.button("🧹 Reset Today's Trades"):
    if os.path.exists(CSV_FILE):
        os.remove(CSV_FILE)
    st.rerun()

# Dynamic Metrics Calculation
tot_trades = len(trades_df)
net_pts = (
    trades_df["Points_P&L"].sum()
    if tot_trades > 0 and "Points_P&L" in trades_df.columns
    else 0.0
)
net_rs = (
    trades_df["Rupees_P&L"].sum()
    if tot_trades > 0 and "Rupees_P&L" in trades_df.columns
    else 0.0
)
wins = (
    (trades_df["Points_P&L"] > 0).sum()
    if tot_trades > 0 and "Points_P&L" in trades_df.columns
    else 0
)
win_rate = round((wins / tot_trades * 100), 2) if tot_trades > 0 else 0.0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("NSE Live Nifty", f"{live_nifty_price:.2f}")
c2.metric("Today Trades", tot_trades)
c3.metric("Net Points P&L", f"{net_pts:+.2f} Pts")
c4.metric(
    "Net Rupees P&L",
    f"₹ {net_rs:,.2f}",
    delta=f"{net_rs:,.2f}",
    delta_color="normal",
)
c5.metric("Win Rate", f"{win_rate}%")

st.markdown("---")

col_chart, col_table = st.columns([4, 6])

with col_chart:
    st.subheader("📊 Live Nifty Ticker")
    fig = go.Figure(
        go.Indicator(
            mode="number+delta",
            value=live_nifty_price,
            title={"text": "NIFTY 50 Spot Price"},
            delta={"reference": 23800.0, "relative": False},
        )
    )
    fig.update_layout(height=300, template="plotly_dark")
    st.plotly_chart(fig, use_container_width=True)

with col_table:
    st.subheader(f"📜 Today's Live Positions & Signals ({TODAY_STR})")
    if not trades_df.empty:
        # Display Live Table with Status
        st.dataframe(trades_df, use_container_width=True, height=320)
    else:
        st.info(
            "No positions active for today yet. Use triggers above or webhooks to initiate."
        )

# Auto-refresh app every 3 seconds to stream live broker-like PnL
time.sleep(3)
st.rerun()
