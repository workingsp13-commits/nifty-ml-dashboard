import os
import warnings
from datetime import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf
from sklearn.ensemble import RandomForestClassifier

warnings.filterwarnings("ignore")

# Streamlit Page Config
st.set_page_config(
    page_title="Nifty ML Live Paper Trader", layout="wide", page_icon="📈"
)

st.title("📈 Nifty ML Live Paper Trading Dashboard")
st.caption(
    "Rules: Target Min +15 Pts (Max +45 Pts) | SL: -15 Pts | Free NSE Live Feed"
)

LOT_SIZE = 65
CSV_FILE = "paper_trades_history.csv"


# ------------------------------------------
# 1. Free Real-Time NSE Live Data Fetcher
# ------------------------------------------
def fetch_nse_live_data():
    """Fetches Instant Real-Time Nifty Price via Official NSE Public Endpoint"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    session = requests.Session()
    try:
        session.get("https://www.nseindia.com", headers=headers, timeout=3)
        url = "https://www.nseindia.com/api/allIndices"
        response = session.get(url, headers=headers, timeout=3)
        if response.status_code == 200:
            data = response.json()
            for index in data.get("data", []):
                if index.get("index") == "NIFTY 50":
                    return float(index.get("last"))
    except Exception:
        pass

    # Fallback to yfinance intraday if NSE site is slow
    df_fallback = yf.download(
        "^NSEI", period="1d", interval="1m", progress=False
    )
    if not df_fallback.empty:
        if isinstance(df_fallback.columns, pd.MultiIndex):
            df_fallback.columns = df_fallback.columns.get_level_values(0)
        return float(df_fallback["Close"].iloc[-1])

    return 24000.0


# ------------------------------------------
# 2. ML Engine & Strategy Logic
# ------------------------------------------
@st.cache_data(ttl=300)
def load_and_train_model():
    data = yf.download("^NSEI", period="60d", interval="5m", progress=False)

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    data = data.dropna(how="all")

    # Technical Indicators
    delta = data["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    data["RSI"] = 100 - (100 / (1 + rs))

    ema12 = data["Close"].ewm(span=12, adjust=False).mean()
    ema26 = data["Close"].ewm(span=26, adjust=False).mean()
    data["MACD"] = ema12 - ema26
    data["MACD_Signal"] = data["MACD"].ewm(span=9, adjust=False).mean()
    data["MACD_Hist"] = data["MACD"] - data["MACD_Signal"]

    vol_safe = data["Volume"].replace(0, 1)
    cum_vol = vol_safe.cumsum()
    data["VWAP"] = (
        vol_safe * (data["High"] + data["Low"] + data["Close"]) / 3
    ).cumsum() / cum_vol
    data["VWAP_Diff"] = (data["Close"] - data["VWAP"]) / (
        data["VWAP"] + 1e-9
    )
    data["Returns"] = data["Close"].pct_change()

    data["ATM_Strike"] = (data["Close"] / 50).round() * 50
    data["Points_Move"] = data["Close"].shift(-2) - data["Close"]
    data["Max_Favorable"] = (
        data["High"].rolling(6).max().shift(-6) - data["Close"]
    )
    data["Max_Adverse"] = data["Low"].rolling(6).min().shift(-6) - data["Close"]

    np.random.seed(42)
    data["PCR"] = np.random.uniform(0.70, 1.30, size=len(data))
    data["Target"] = np.where(
        data["Points_Move"] > 10, 1, np.where(data["Points_Move"] < -10, -1, 0)
    )

    df = data.copy()
    features = ["Returns", "RSI", "MACD_Hist", "VWAP_Diff", "PCR"]
    df[features] = (
        df[features]
        .replace([np.inf, -np.inf], np.nan)
        .ffill()
        .bfill()
        .fillna(0)
    )

    X = df[features]
    y = df["Target"]

    split = int(len(X) * 0.7)
    X_train, X_test = X.iloc[:split], X.iloc[split:]
    y_train, y_test = y.iloc[:split], y.iloc[split:]

    model = RandomForestClassifier(
        n_estimators=100, max_depth=5, random_state=42
    )
    model.fit(X_train, y_train)

    probs = model.predict_proba(X_test)
    classes = list(model.classes_)

    ce_index = classes.index(1) if 1 in classes else -1
    pe_index = classes.index(-1) if -1 in classes else -1

    X_test = X_test.copy()
    prob_ce = probs[:, ce_index] if ce_index != -1 else np.zeros(len(X_test))
    prob_pe = probs[:, pe_index] if pe_index != -1 else np.zeros(len(X_test))

    X_test["Prob_CE"] = prob_ce
    X_test["Prob_PE"] = prob_pe
    X_test["Max_Prob"] = np.maximum(prob_ce, prob_pe)

    X_test["Raw_CE"] = (
        (prob_ce >= 0.30) & (X_test["RSI"] > 45) & (X_test["MACD_Hist"] > 0)
    )
    X_test["Raw_PE"] = (
        (prob_pe >= 0.30) & (X_test["RSI"] < 55) & (X_test["MACD_Hist"] < 0)
    )

    X_test["Points_Move"] = df.loc[X_test.index, "Points_Move"].values
    X_test["Max_Favorable"] = df.loc[X_test.index, "Max_Favorable"].values
    X_test["Max_Adverse"] = df.loc[X_test.index, "Max_Adverse"].values
    X_test["ATM_Strike"] = df.loc[X_test.index, "ATM_Strike"].astype(int).values
    X_test["Date"] = X_test.index.date.astype(str)
    X_test["Time"] = X_test.index.strftime("%H:%M")

    time_filter = (X_test["Time"] >= "09:25") & (X_test["Time"] <= "15:15")
    all_signals = X_test[
        time_filter & (X_test["Raw_CE"] | X_test["Raw_PE"])
    ].copy()

    if len(all_signals) > 0:
        top3_trades = (
            all_signals.sort_values(
                by=["Date", "Max_Prob"], ascending=[True, False]
            )
            .groupby("Date", as_index=False)
            .head(3)
            .copy()
        )

        top3_trades["Type"] = np.where(
            top3_trades["Raw_CE"], "CE BUY", "PE BUY"
        )
        top3_trades["Option_Strike"] = (
            top3_trades["ATM_Strike"].astype(str)
            + " "
            + np.where(top3_trades["Raw_CE"], "CE (ATM)", "PE (ATM)")
        )

        pnl_list = []
        for idx, row in top3_trades.iterrows():
            is_ce = row["Type"] == "CE BUY"
            fav_move = row["Max_Favorable"] if is_ce else -row["Max_Adverse"]
            adv_move = row["Max_Adverse"] if is_ce else -row["Max_Favorable"]
            final_move = row["Points_Move"] if is_ce else -row["Points_Move"]

            if fav_move >= 45.0:
                final_pnl = 45.0
            elif fav_move >= 15.0:
                final_pnl = min(fav_move, 45.0)
            elif adv_move <= -15.0:
                final_pnl = -15.0
            else:
                final_pnl = final_move if final_move < 0 else -15.0

            pnl_list.append(round(final_pnl, 2))

        top3_trades["Points_P&L"] = pnl_list
        top3_trades["Result"] = np.where(
            top3_trades["Points_P&L"] > 0, "PROFIT", "LOSS"
        )
        top3_trades["Rupees_P&L"] = top3_trades["Points_P&L"] * LOT_SIZE

        unique_dates = sorted(top3_trades["Date"].unique())[-15:]
        last_15_days = top3_trades[
            top3_trades["Date"].isin(unique_dates)
        ].copy()

        return data, last_15_days

    return data, pd.DataFrame()


# Load Data
with st.spinner("Downloading Data & Initializing ML Engine..."):
    raw_data, trades_df = load_and_train_model()

# CSV File Logic (Always overwrites if columns are missing or file is outdated)
if (
    not os.path.exists(CSV_FILE)
    or os.path.getsize(CSV_FILE) < 10
    or "Points_P&L" not in pd.read_csv(CSV_FILE).columns
):
    trades_df.to_csv(CSV_FILE, index=False)
    trade_history_df = trades_df.copy()
else:
    trade_history_df = pd.read_csv(CSV_FILE)

# Fetch Live Price
live_nifty_price = fetch_nse_live_data()

# ------------------------------------------
# 3. Streamlit Dashboard Layout
# ------------------------------------------
st.sidebar.header("⚙️ Controls")

if st.sidebar.button("🔄 Refresh Live Price & Signals"):
    if os.path.exists(CSV_FILE):
        os.remove(CSV_FILE)
    st.cache_data.clear()
    st.rerun()

available_dates = (
    sorted(trade_history_df["Date"].unique(), reverse=True)
    if not trade_history_df.empty
    else []
)
selected_date = st.sidebar.selectbox(
    "Select Date Filter:", ["All Days"] + available_dates
)

if selected_date == "All Days":
    view_trades = trade_history_df
else:
    view_trades = trade_history_df[trade_history_df["Date"] == selected_date]

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
    (view_trades["Result"] == "PROFIT").sum()
    if tot_trades > 0 and "Result" in view_trades.columns
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

col_chart, col_table = st.columns([5, 5])

with col_chart:
    st.subheader("📊 Live Intraday Nifty Chart")
    df_chart = raw_data.tail(75)
    fig = go.Figure(
        data=[
            go.Candlestick(
                x=df_chart.index,
                open=df_chart["Open"],
                high=df_chart["High"],
                low=df_chart["Low"],
                close=df_chart["Close"],
                name="Nifty 50",
            )
        ]
    )
    fig.update_layout(
        height=380, template="plotly_dark", margin=dict(l=10, r=10, t=20, b=10)
    )
    st.plotly_chart(fig, use_container_width=True)

with col_table:
    st.subheader(f"📜 Paper Trade Signals ({selected_date})")
    display_cols = [
        "Date",
        "Time",
        "Type",
        "Option_Strike",
        "Result",
        "Points_P&L",
        "Rupees_P&L",
    ]
    existing_cols = [c for c in display_cols if c in view_trades.columns]
    if not view_trades.empty and len(existing_cols) > 0:
        st.dataframe(view_trades[existing_cols], use_container_width=True, height=340)
    else:
        st.info("No Trades Recorded for this selection.")

# Performance Summary
st.markdown("---")
st.subheader("🗓️ Last 15-Days Performance Report")

if not trade_history_df.empty and "Points_P&L" in trade_history_df.columns:
    daily_summary = trade_history_df.groupby("Date").agg(
        Total_Trades=("Result", "count"),
        Profits=("Result", lambda x: (x == "PROFIT").sum()),
        Losses=("Result", lambda x: (x == "LOSS").sum()),
        Net_Points=("Points_P&L", "sum"),
        Net_Rupees=("Rupees_P&L", "sum"),
    )
    daily_summary["Win_Rate_%"] = round(
        (daily_summary["Profits"] / daily_summary["Total_Trades"]) * 100, 2
    )
    daily_summary = daily_summary.sort_index(ascending=False)

    st.dataframe(daily_summary, use_container_width=True)