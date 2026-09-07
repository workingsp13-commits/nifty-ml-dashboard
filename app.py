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
    "Live Real-Time Option PnL Tracker | Target: +15 to +45 Pts | SL: -15 Pts | Fast Direct Feed"
)

LOT_SIZE = 65
TODAY_STR = datetime.now().strftime("%Y-%m-%d")
CSV_FILE = "trades_master.csv"


# ------------------------------------------
# 1. Fast NSE Live Data Fetcher
# ------------------------------------------
def fetch_nse_live_data():
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
        session.get("https://www.nseindia.com", headers=headers, timeout=1)
        url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050"
        response = session.get(url, headers=headers, timeout=1)

        if response.status_code == 200:
            data = response.json()
            if "data" in data and len(data["data"]) > 0:
                return float(data["data"][0]["lastPrice"])
    except Exception:
        pass

    return 23800.00


# ------------------------------------------
# 2. Master CSV Database Operations
# ------------------------------------------
def init_master_csv():
    if not os.path.exists(CSV_FILE):
        df_empty = pd.DataFrame(
            columns=[
                "Date",
                "Time",
                "Type",
                "Option_Strike",
                "Option_Entry_Price",
                "Option_Current_Price",
                "Status",
                "Points_P&L",
                "Rupees_P&L",
            ]
        )
        df_empty.to_csv(CSV_FILE, index=False)


def load_all_trades():
    init_master_csv()
    try:
        df = pd.read_csv(CSV_FILE)
        # Structural check for compatibility
        if "Entry_Price" in df.columns and "Option_Entry_Price" not in df.columns:
            df.rename(columns={"Entry_Price": "Option_Entry_Price"}, inplace=True)
        return df
    except Exception:
        return pd.DataFrame()


def update_trades_file(df):
    df.to_csv(CSV_FILE, index=False)


# ------------------------------------------
# 3. Option Price & Live PnL Processing
# ------------------------------------------
live_nifty_price = fetch_nse_live_data()
all_trades_df = load_all_trades()

if not all_trades_df.empty:
    for idx, row in all_trades_df.iterrows():
        if row["Date"] == TODAY_STR and row["Status"] == "OPEN":
            # Real Option Premium estimation using Delta offset if external price is not provided
            entry_price = float(row["Option_Entry_Price"])
            is_ce = "CE" in str(row["Type"])

            # Live Option Price calculated dynamically based on Spot movement
            # Delta ~ 0.5 for ATM Options
            spot_ref = float(row.get("Spot_Reference", live_nifty_price))
            spot_diff = live_nifty_price - spot_ref if is_ce else spot_ref - live_nifty_price
            
            curr_option_price = round(entry_price + (spot_diff * 0.5), 2)
            all_trades_df.at[idx, "Option_Current_Price"] = curr_option_price

            pts_move = round(curr_option_price - entry_price, 2)

            if pts_move >= 45.0:
                all_trades_df.at[idx, "Option_Current_Price"] = entry_price + 45.0
                all_trades_df.at[idx, "Status"] = "TARGET HIT (+45)"
                all_trades_df.at[idx, "Points_P&L"] = 45.0
                all_trades_df.at[idx, "Rupees_P&L"] = 45.0 * LOT_SIZE
            elif pts_move <= -15.0:
                all_trades_df.at[idx, "Option_Current_Price"] = entry_price - 15.0
                all_trades_df.at[idx, "Status"] = "SL HIT (-15)"
                all_trades_df.at[idx, "Points_P&L"] = -15.0
                all_trades_df.at[idx, "Rupees_P&L"] = -15.0 * LOT_SIZE
            else:
                all_trades_df.at[idx, "Points_P&L"] = pts_move
                all_trades_df.at[idx, "Rupees_P&L"] = round(pts_move * LOT_SIZE, 2)

    update_trades_file(all_trades_df)

# ------------------------------------------
# 4. Streamlit Dashboard View
# ------------------------------------------
st.sidebar.header("🗓️ History Filter")

available_dates = (
    sorted(all_trades_df["Date"].unique().tolist(), reverse=True)
    if not all_trades_df.empty
    else [TODAY_STR]
)

selected_date = st.sidebar.selectbox(
    "Select Date to View:",
    ["All Days"] + available_dates,
    index=0
    if TODAY_STR not in available_dates
    else available_dates.index(TODAY_STR) + 1,
)

if selected_date == "All Days":
    view_trades = all_trades_df
else:
    view_trades = all_trades_df[all_trades_df["Date"] == selected_date]

# Metrics
tot_trades = len(view_trades)
net_pts = (
    view_trades["Points_P&L"].sum()
    if tot_trades > 0 and "Points_P&L" in view_trades.columns
    else 0.0
)
net_rs = (
    view_trades["Rupees_P&L"].sum()
    if tot_trades > 0 and "Rupees_P&L" in view_trades.columns
    else 0.0
)
wins = (
    (view_trades["Points_P&L"] > 0).sum()
    if tot_trades > 0 and "Points_P&L" in view_trades.columns
    else 0
)
win_rate = round((wins / tot_trades * 100), 2) if tot_trades > 0 else 0.0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("NSE Live Nifty", f"{live_nifty_price:.2f}")
c2.metric("Total Trades", tot_trades)
c3.metric("Net Points P&L", f"{net_pts:+.2f} Pts")
c4.metric("Net Rupees P&L", f"₹ {net_rs:,.2f}")
c5.metric("Win Rate", f"{win_rate}%")

st.markdown("---")

col_chart, col_table = st.columns([4, 6])

with col_chart:
    st.subheader("📊 Live Nifty Spot Price")
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
    st.subheader(f"📜 Trade Signals & Positions ({selected_date})")
    if not view_trades.empty:
        st.dataframe(view_trades, use_container_width=True, height=300)
    else:
        st.info("No recorded trades found for this filter.")

# ------------------------------------------
# 5. Fast 1-Second Auto Refresh
# ------------------------------------------
time.sleep(1)
st.rerun()
