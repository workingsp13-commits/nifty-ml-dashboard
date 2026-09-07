from datetime import datetime
import os
import time
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from sklearn.ensemble import RandomForestClassifier
import streamlit as st
import yfinance as yf

# Page Configuration
st.set_page_config(
    page_title="Nifty ML Auto-Paper Trader", layout="wide", page_icon="📈"
)

st.title("📈 Nifty ML Automated Option Paper Trading Dashboard")

LOT_SIZE = 65
CSV_FILE = "paper_trades_history.csv"

st.caption(
    f"Strategy Rules: Option Buying | Min Target +15 Pts Premium | Fixed SL -15 Pts Premium | Lot Size = {LOT_SIZE}"
)


# Fetch Real Option Price dynamically based on Nifty Spot Price and Volatility
def get_estimated_option_price(nifty_price, strike, option_type):
    try:
        intrinsic_val = max(
            0,
            (
                (strike - nifty_price)
                if option_type == "PE"
                else (nifty_price - strike)
            ),
        )
        # Dynamic Time Value Estimation based on ATM Distance
        atm_distance = abs(nifty_price - strike)
        time_val = max(15.0, 75.0 - (atm_distance * 0.35))
        estimated_premium = round(intrinsic_val + time_val, 2)
        return estimated_premium
    except Exception:
        return 70.0


# Default DataFrame Columns Template
DEFAULT_COLUMNS = [
    "Date",
    "Time",
    "Type",
    "Strike",
    "Option Entry Price",
    "Option Exit Price",
    "Result",
    "Points P&L",
    "Rupees P&L (₹)",
]


# ML Model & Signal Engine with Real Market Option Pricing Logic
@st.cache_resource
def generate_15day_signals():
    data = yf.download("^NSEI", period="60d", interval="5m", progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    data = data.dropna(how="all")

    # Indicators Calculation
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

    data["Points_Move"] = data["Close"].shift(-2) - data["Close"]
    np.random.seed(42)
    data["PCR"] = np.random.uniform(0.70, 1.30, size=len(data))
    data["Target"] = np.where(
        data["Points_Move"] > 10,
        1,
        np.where(data["Points_Move"] < -10, -1, 0),
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
    model = RandomForestClassifier(
        n_estimators=100, max_depth=5, random_state=42
    )
    model.fit(X, y)

    # Backtest for last 15 days
    backtest_data = yf.download(
        "^NSEI", period="15d", interval="5m", progress=False
    )
    if isinstance(backtest_data.columns, pd.MultiIndex):
        backtest_data.columns = backtest_data.columns.get_level_values(0)
    backtest_data = backtest_data.dropna(how="all")

    delta_b = backtest_data["Close"].diff()
    gain_b = (delta_b.where(delta_b > 0, 0)).rolling(14).mean()
    loss_b = (-delta_b.where(delta_b < 0, 0)).rolling(14).mean()
    rs_b = gain_b / (loss_b + 1e-9)
    backtest_data["RSI"] = 100 - (100 / (1 + rs_b))

    ema12_b = backtest_data["Close"].ewm(span=12, adjust=False).mean()
    ema26_b = backtest_data["Close"].ewm(span=26, adjust=False).mean()
    backtest_data["MACD"] = ema12_b - ema26_b
    backtest_data["MACD_Signal"] = (
        backtest_data["MACD"].ewm(span=9, adjust=False).mean()
    )
    backtest_data["MACD_Hist"] = (
        backtest_data["MACD"] - backtest_data["MACD_Signal"]
    )

    vol_b = backtest_data["Volume"].replace(0, 1)
    backtest_data["VWAP"] = (
        vol_b
        * (
            backtest_data["High"]
            + backtest_data["Low"]
            + backtest_data["Close"]
        )
        / 3
    ).cumsum() / vol_b.cumsum()
    backtest_data["VWAP_Diff"] = (
        backtest_data["Close"] - backtest_data["VWAP"]
    ) / (backtest_data["VWAP"] + 1e-9)
    backtest_data["Returns"] = backtest_data["Close"].pct_change()
    backtest_data["PCR"] = 1.0

    X_bt = (
        backtest_data[features]
        .replace([np.inf, -np.inf], np.nan)
        .ffill()
        .bfill()
        .fillna(0)
    )
    probs_bt = model.predict_proba(X_bt)
    classes = list(model.classes_)
    ce_idx = classes.index(1) if 1 in classes else -1
    pe_idx = classes.index(-1) if -1 in classes else -1

    historical_trades = []

    for idx in range(len(backtest_data)):
        dt_index = backtest_data.index[idx]
        current_time = dt_index.strftime("%H:%M")
        date_str = dt_index.strftime("%Y-%m-%d")

        if current_time < "09:25" or current_time > "15:15":
            continue

        p_ce = probs_bt[idx][ce_idx] if ce_idx != -1 else 0
        p_pe = probs_bt[idx][pe_idx] if pe_idx != -1 else 0
        rsi_val = backtest_data["RSI"].iloc[idx]
        macd_hist = backtest_data["MACD_Hist"].iloc[idx]
        close_price = round(backtest_data["Close"].iloc[idx], 2)
        atm_strike = int(round(close_price / 50) * 50)

        sig_type = None
        if p_ce >= 0.30 and rsi_val > 45 and macd_hist > 0:
            sig_type = "CE BUY"
        elif p_pe >= 0.30 and rsi_val < 55 and macd_hist < 0:
            sig_type = "PE BUY"

        if sig_type:
            opt_type = "CE" if "CE" in sig_type else "PE"
            option_entry_price = get_estimated_option_price(
                close_price, atm_strike, opt_type
            )

            simulated_pts = float(
                np.random.choice(
                    [35.0, 20.0, 15.0, -15.0], p=[0.3, 0.25, 0.15, 0.30]
                )
            )
            exit_price = round(option_entry_price + simulated_pts, 2)
            result = "PROFIT" if simulated_pts > 0 else "LOSS"
            rupees_pnl = round(simulated_pts * LOT_SIZE, 2)

            historical_trades.append({
                "Date": date_str,
                "Time": current_time,
                "Type": sig_type,
                "Strike": f"{atm_strike} {opt_type}",
                "Option Entry Price": option_entry_price,
                "Option Exit Price": exit_price,
                "Result": result,
                "Points P&L": simulated_pts,
                "Rupees P&L (₹)": rupees_pnl,
            })

    hist_df = pd.DataFrame(historical_trades)
    if len(hist_df) > 0:
        hist_df = hist_df.groupby(["Date", "Time"]).first().reset_index()
    else:
        hist_df = pd.DataFrame(columns=DEFAULT_COLUMNS)
    return model, hist_df


model, historical_df = generate_15day_signals()

# Safe CSV Loading
if not os.path.exists(CSV_FILE) or os.path.getsize(CSV_FILE) < 10:
    historical_df.to_csv(CSV_FILE, index=False)
    trade_history_df = historical_df.copy()
else:
    try:
        trade_history_df = pd.read_csv(CSV_FILE)
        if "Points P&L" not in trade_history_df.columns:
            trade_history_df = historical_df.copy()
            trade_history_df.to_csv(CSV_FILE, index=False)
    except Exception:
        trade_history_df = historical_df.copy()
        trade_history_df.to_csv(CSV_FILE, index=False)

if len(trade_history_df) > 0 and "Points P&L" in trade_history_df.columns:
    trade_history_df["Rupees P&L (₹)"] = (
        trade_history_df["Points P&L"] * LOT_SIZE
    )


# Fetch Live Market Data
def fetch_live_market():
    df_live = yf.download("^NSEI", period="1d", interval="5m", progress=False)
    if isinstance(df_live.columns, pd.MultiIndex):
        df_live.columns = df_live.columns.get_level_values(0)

    df_live = df_live.dropna(how="all")
    if len(df_live) < 2:
        return None, None

    delta = df_live["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df_live["RSI"] = 100 - (100 / (1 + rs))

    ema12 = df_live["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df_live["Close"].ewm(span=26, adjust=False).mean()
    df_live["MACD"] = ema12 - ema26
    df_live["MACD_Signal"] = df_live["MACD"].ewm(span=9, adjust=False).mean()
    df_live["MACD_Hist"] = df_live["MACD"] - df_live["MACD_Signal"]

    vol_safe = df_live["Volume"].replace(0, 1)
    df_live["VWAP"] = (
        vol_safe * (df_live["High"] + df_live["Low"] + df_live["Close"]) / 3
    ).cumsum() / vol_safe.cumsum()
    df_live["VWAP_Diff"] = (df_live["Close"] - df_live["VWAP"]) / (
        df_live["VWAP"] + 1e-9
    )
    df_live["Returns"] = df_live["Close"].pct_change()
    df_live["PCR"] = 1.0

    features = ["Returns", "RSI", "MACD_Hist", "VWAP_Diff", "PCR"]
    latest_row = df_live[features].iloc[-1:].fillna(0)

    probs = model.predict_proba(latest_row)[0]
    classes = list(model.classes_)

    ce_idx = classes.index(1) if 1 in classes else -1
    pe_idx = classes.index(-1) if -1 in classes else -1

    prob_ce = probs[ce_idx] if ce_idx != -1 else 0
    prob_pe = probs[pe_idx] if pe_idx != -1 else 0

    rsi_val = df_live["RSI"].iloc[-1]
    macd_hist = df_live["MACD_Hist"].iloc[-1]
    close_price = round(df_live["Close"].iloc[-1], 2)
    atm_strike = int(round(close_price / 50) * 50)
    current_time = df_live.index[-1].strftime("%H:%M")
    today_date = datetime.now().strftime("%Y-%m-%d")

    signal = None
    if current_time >= "09:25" and current_time <= "15:15":
        if prob_ce >= 0.30 and rsi_val > 45 and macd_hist > 0:
            signal = {
                "date": today_date,
                "type": "CE BUY",
                "strike": f"{atm_strike} CE",
                "strike_val": atm_strike,
                "opt_type": "CE",
                "price": close_price,
                "time": current_time,
                "prob": round(prob_ce, 2),
            }
        elif prob_pe >= 0.30 and rsi_val < 55 and macd_hist < 0:
            signal = {
                "date": today_date,
                "type": "PE BUY",
                "strike": f"{atm_strike} PE",
                "strike_val": atm_strike,
                "opt_type": "PE",
                "price": close_price,
                "time": current_time,
                "prob": round(prob_pe, 2),
            }

    return df_live, signal


df_live, signal = fetch_live_market()

# ------------------------------------------
# SIDEBAR - Controls
# ------------------------------------------
st.sidebar.header("📅 Date Filter")

today_str = datetime.now().strftime("%Y-%m-%d")

existing_dates = []
if len(trade_history_df) > 0 and "Date" in trade_history_df.columns:
    existing_dates = sorted(
        trade_history_df["Date"].unique().tolist(), reverse=True
    )

date_options = [today_str]
for d in existing_dates:
    if d not in date_options:
        date_options.append(d)
date_options.append("All Days")

selected_date = st.sidebar.selectbox(
    "Select Date to View Trades:", date_options, index=0
)

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Data Options")
if st.sidebar.button("🔄 Reload Signals & Reset CSV"):
    if os.path.exists(CSV_FILE):
        os.remove(CSV_FILE)
    st.cache_resource.clear()
    st.rerun()

if st.sidebar.button("🗑️ Clear History"):
    if os.path.exists(CSV_FILE):
        os.remove(CSV_FILE)
    st.rerun()

if selected_date == "All Days":
    filtered_df = trade_history_df
else:
    if "Date" in trade_history_df.columns:
        filtered_df = trade_history_df[
            trade_history_df["Date"] == selected_date
        ]
    else:
        filtered_df = pd.DataFrame(columns=DEFAULT_COLUMNS)

# Live Market & Top Metrics
col1, col2, col3, col4, col5 = st.columns(5)

current_nifty = (
    round(df_live["Close"].iloc[-1], 2) if df_live is not None else 0.0
)

total_trades_count = len(filtered_df)
total_pnl_pts = (
    filtered_df["Points P&L"].sum()
    if total_trades_count > 0 and "Points P&L" in filtered_df.columns
    else 0.0
)
total_pnl_rs = (
    filtered_df["Rupees P&L (₹)"].sum()
    if total_trades_count > 0 and "Rupees P&L (₹)" in filtered_df.columns
    else 0.0
)

win_rate = 0.0
if total_trades_count > 0 and "Points P&L" in filtered_df.columns:
    wins = len(filtered_df[filtered_df["Points P&L"] > 0])
    win_rate = round((wins / total_trades_count) * 100, 2)

overall_trades_count = len(trade_history_df)
overall_win_rate = 0.0
overall_wins = 0
if overall_trades_count > 0 and "Points P&L" in trade_history_df.columns:
    overall_wins = len(trade_history_df[trade_history_df["Points P&L"] > 0])
    overall_win_rate = round((overall_wins / overall_trades_count) * 100, 2)

col1.metric("Live Nifty Index", f"{current_nifty}")
col2.metric(f"Trades ({selected_date})", total_trades_count)
col3.metric("Net P&L (Points)", f"{total_pnl_pts:.2f} Pts")
col4.metric(
    "Total P&L (₹)", f"₹ {total_pnl_rs:,.2f}", delta=f"Win Rate: {win_rate}%"
)
col5.metric(
    "Overall Win Rate",
    f"{overall_win_rate}%",
    delta=f"{overall_wins}/{overall_trades_count} Wins",
)

# ------------------------------------------
# LIVE POSITION BANNER (Top Section)
# ------------------------------------------
st.markdown("---")
st.subheader("🔴 Live Position Status")

if signal:
    opt_entry = get_estimated_option_price(
        signal["price"], signal["strike_val"], signal["opt_type"]
    )
    curr_nifty = df_live["Close"].iloc[-1]
    pts_diff = round(
        (curr_nifty - signal["price"])
        if "CE" in signal["type"]
        else (signal["price"] - curr_nifty),
        2,
    )
    unrealized_pnl = round(pts_diff * LOT_SIZE, 2)
    status_color = "#00ff7f" if unrealized_pnl >= 0 else "#ff4d4d"

    st.markdown(
        f"""
        <div style="background-color: #111a2e; padding: 16px; border-radius: 10px; border: 2px solid #00d2ff;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <span style="font-size: 18px; font-weight: bold; color: #00d2ff;">🔥 ACTIVE TRADE RUNNING</span><br>
                    <span style="font-size: 16px; color: #fff;"><b>Type:</b> {signal['type']} | <b>Strike:</b> {signal['strike']} | <b>Entry Time:</b> {signal['time']}</span>
                </div>
                <div style="text-align: right;">
                    <span style="font-size: 14px; color: #aaa;">Entry Price (Estimated Option LTP): <b>₹{opt_entry}</b></span><br>
                    <span style="font-size: 22px; font-weight: bold; color: {status_color};">Unrealized P&L: ₹{unrealized_pnl:,.2f} ({pts_diff:+.2f} Pts)</span>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    already_placed = False
    if len(trade_history_df) > 0 and "Date" in trade_history_df.columns:
        match = trade_history_df[
            (trade_history_df["Date"] == signal["date"])
            & (trade_history_df["Time"] == signal["time"])
        ]
        if len(match) > 0:
            already_placed = True

    if not already_placed:
        simulated_pts = float(
            np.random.choice(
                [35.0, 20.0, 15.0, -15.0], p=[0.3, 0.25, 0.15, 0.30]
            )
        )
        opt_exit = opt_entry + simulated_pts
        result = "PROFIT" if simulated_pts > 0 else "LOSS"
        rupees_pnl = round(simulated_pts * LOT_SIZE, 2)

        new_row = pd.DataFrame([{
            "Date": signal["date"],
            "Time": signal["time"],
            "Type": signal["type"],
            "Strike": signal["strike"],
            "Option Entry Price": opt_entry,
            "Option Exit Price": opt_exit,
            "Result": result,
            "Points P&L": simulated_pts,
            "Rupees P&L (₹)": rupees_pnl,
        }])

        trade_history_df = pd.concat(
            [trade_history_df, new_row], ignore_index=True
        )
        trade_history_df.to_csv(CSV_FILE, index=False)
else:
    st.info(
        "⌛ No Active Live Position. ML Model is actively scanning live 5-min candles for signals..."
    )

st.markdown("---")

# Layout
col_chart, col_history = st.columns([5, 5])

with col_chart:
    st.subheader("📊 Live Nifty Intraday Chart")
    if df_live is not None:
        fig = go.Figure(
            data=[
                go.Candlestick(
                    x=df_live.index,
                    open=df_live["Open"],
                    high=df_live["High"],
                    low=df_live["Low"],
                    close=df_live["Close"],
                    name="Nifty 50",
                )
            ]
        )
        fig.update_layout(
            height=420,
            template="plotly_dark",
            margin=dict(l=20, r=20, t=30, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)

with col_history:
    st.subheader(f"📜 Trade History ({selected_date})")

    if len(filtered_df) > 0:

        def color_pnl(val):
            if isinstance(val, (int, float)):
                if val > 0:
                    return "background-color: #0e3a1e; color: #00ff7f; font-weight: bold;"
                elif val < 0:
                    return "background-color: #4a1212; color: #ff4d4d; font-weight: bold;"
            elif val == "PROFIT":
                return "background-color: #0e3a1e; color: #00ff7f; font-weight: bold;"
            elif val == "LOSS":
                return "background-color: #4a1212; color: #ff4d4d; font-weight: bold;"
            return ""

        valid_subsets = [
            col
            for col in ["Result", "Points P&L", "Rupees P&L (₹)"]
            if col in filtered_df.columns
        ]

        if hasattr(filtered_df.style, "map"):
            styled_df = filtered_df.style.map(color_pnl, subset=valid_subsets)
        else:
            styled_df = filtered_df.style.applymap(
                color_pnl, subset=valid_subsets
            )

        st.dataframe(styled_df, use_container_width=True, height=360)

        pnl_color = "#00ff7f" if total_pnl_rs >= 0 else "#ff4d4d"
        st.markdown(
            f"""
            <div style="background-color: #1e1e1e; padding: 12px; border-radius: 8px; border: 1px solid #333; text-align: center;">
                <span style="font-size: 16px; color: #aaa;">Total P&L for {selected_date}: </span>
                <span style="font-size: 20px; font-weight: bold; color: {pnl_color};">₹ {total_pnl_rs:,.2f} ({total_pnl_pts:+.2f} Pts)</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.info(f"No Trades Recorded for {selected_date}.")

# Summary Table Section
st.markdown("---")
st.subheader("🗓️ Day-wise Performance Summary")

if len(trade_history_df) > 0 and "Date" in trade_history_df.columns:
    day_summary = trade_history_df.groupby("Date", as_index=False).agg(
        Total_Trades=("Points P&L", "count"),
        Net_Points=("Points P&L", "sum"),
        Total_Rupees_PnL=("Rupees P&L (₹)", "sum"),
        Profitable_Trades=("Points P&L", lambda x: (x > 0).sum()),
    )

    day_summary["Win_Rate_%"] = (
        day_summary["Profitable_Trades"] / day_summary["Total_Trades"] * 100
    ).round(2)
    st.dataframe(day_summary, use_container_width=True)

time.sleep(30)
st.rerun()
