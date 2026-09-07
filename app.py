import os
import time
import warnings
from datetime import datetime
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


# ------------------------------------------
# 1. Direct NSE Live Data Fetcher
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

    if os.path.exists(CSV_FILE):
        try:
            df_temp = pd.read_csv(CSV_FILE)
            if not df_temp.empty and "Entry_Price" in df_temp.columns:
                return float(df_temp["Entry_Price"].iloc[-1])
        except Exception:
            pass
    return 23800.00


# ------------------------------------------
# 2. Local CSV Data Management (Persistent Log)
# ------------------------------------------
def init_today_csv():
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
        return pd.read_csv(CSV_FILE)
    except Exception:
        return pd.DataFrame()


def update_trades_file(df):
    df.to_csv(CSV_FILE, index=False)


# ------------------------------------------
# 3. Live Price & Position Processing
# ------------------------------------------
live_nifty_price = fetch_nse_live_data()
trades_df = load_today_trades()

# Real-time Position Live Stream Engine
if not trades_df.empty:
    for idx, row in trades_df.iterrows():
        if row["Status"] == "OPEN":
            entry = float(row["Entry_Price"])
            is_ce = "CE" in str(row["Type"])

            current_move = (
                (live_nifty_price - entry)
                if is_ce
                else (entry - live_nifty_price)
            )

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
                trades_df.at[idx, "Points_P&L"] = round(current_move, 2)
                trades_df.at[idx, "Rupees_P&L"] = round(
                    current_move * LOT_SIZE, 2
                )

    update_trades_file(trades_df)

# ------------------------------------------
# 4. Streamlit Dashboard View
# ------------------------------------------
# Metrics
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
c4.metric("Net Rupees P&L", f"₹ {net_rs:,.2f}")
c5.metric("Win Rate", f"{win_rate}%")

st.markdown("---")

col_chart, col_table = st.columns([4, 6])

with col_chart:
    st.subheader("📊 Live Nifty Spot Price")
    # Display Full Exact Price without 23.8k short formatting
    fig = go.Figure(
        go.Indicator(
            mode="number",
            value=live_nifty_price,
            number={"valueformat": ".2f", "suffix": " Pts"},
            title={"text": "NIFTY 50 Spot Price"},
        )
    )
    fig.update_layout(height=280, template="plotly_dark")
    st.plotly_chart(fig, use_container_width=True)

with col_table:
    st.subheader(f"📜 Today's Live Positions & Signals ({TODAY_STR})")
    if not trades_df.empty:
        st.dataframe(trades_df, use_container_width=True, height=300)
    else:
        st.info("No active positions recorded for today yet.")

# Auto-refresh app every 2 seconds for live stream
time.sleep(2)
st.rerun()
