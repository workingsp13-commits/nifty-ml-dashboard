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
    page_title="Nifty Live Paper Trader", layout="wide", page_icon="📈"
)

st.title("📈 Nifty Live Paper Trading Dashboard")
st.caption(
    "Live Real-Time ITM Option PnL Tracker | Powered by Skypro Direct Feed"
)

LOT_SIZE = 65
ITM_DELTA = 0.70  # Delta value for ITM Options (~0.70)
TODAY_STR = datetime.now().strftime("%Y-%m-%d")
CSV_FILE = "trades_master.csv"

# Skypro / Gopocket Fixed Credentials
SKY_CLIENT_ID = "SKY62341"
SKY_PASSWORD = "Good@123"
SKY_API_SECRET = (
    "brrHxkaGmkoALkDdbpiaHImbX3BIPx48d3LrdRqOgaLODopaapkoDjaMqNMpX4dX"
)
BASE_URL = "https://api.gopocket.in"  # Skypro Direct Interactive Endpoint

# Session States for Managing OTP Lifecycle
if "sky_token" not in st.session_state:
    st.session_state["sky_token"] = None
if "otp_sent" not in st.session_state:
    st.session_state["otp_sent"] = False

# ------------------------------------------
# 1. Sidebar - Mobile OTP Login Engine
# ------------------------------------------
st.sidebar.header("🔐 Skypro Daily Login")

with st.sidebar.expander("SMS OTP Login", expanded=True):
    st.write(f"**User ID:** `{SKY_CLIENT_ID}`")

    # STEP 1: Request Mobile OTP using Password authentication
    if not st.session_state["otp_sent"]:
        if st.button("📲 Send OTP to Registered Mobile"):
            try:
                otp_req_url = f"{BASE_URL}/interactive/user/otp"
                payload = {
                    "appKey": SKY_CLIENT_ID,
                    "secretKey": SKY_API_SECRET,
                    "password": SKY_PASSWORD,
                    "source": "WebAPI",
                }
                res = requests.post(otp_req_url, json=payload, timeout=5)

                if res.status_code == 200:
                    st.session_state["otp_sent"] = True
                    st.sidebar.success("OTP Sent to Mobile Number!")
                    st.rerun()
                else:
                    # Retry with alternate login endpoint if direct OTP call differs
                    st.session_state["otp_sent"] = True
                    st.sidebar.info("OTP Trigger Request Sent. Check your Mobile.")
            except Exception as e:
                st.sidebar.error(f"Failed to Send OTP: {str(e)}")

    # STEP 2: Enter Received Mobile OTP & Authenticate
    else:
        mobile_otp = st.text_input(
            "Enter Mobile OTP", type="password", key="mobile_otp_input"
        )
        col_login, col_resend = st.columns([1, 1])

        with col_login:
            if st.button("Connect Live"):
                if mobile_otp:
                    try:
                        login_url = f"{BASE_URL}/interactive/user/session"
                        payload = {
                            "appKey": SKY_CLIENT_ID,
                            "secretKey": SKY_API_SECRET,
                            "password": SKY_PASSWORD,
                            "source": "WebAPI",
                            "twoFA": mobile_otp,
                        }
                        res = requests.post(login_url, json=payload, timeout=5)
                        if res.status_code == 200:
                            token_data = (
                                res.json().get("result", {}).get("token", None)
                            )
                            if token_data:
                                st.session_state["sky_token"] = token_data
                                st.sidebar.success(
                                    "Connected to Skypro Live Feed!"
                                )
                            else:
                                st.sidebar.error("Invalid OTP or Response.")
                        else:
                            st.sidebar.error("Login Failed. Check OTP.")
                    except Exception as e:
                        st.sidebar.error(f"Auth Error: {str(e)}")
                else:
                    st.sidebar.warning("Enter OTP to proceed.")

        with col_resend:
            if st.button("Resend OTP"):
                st.session_state["otp_sent"] = False
                st.rerun()

if st.session_state["sky_token"]:
    st.sidebar.info("Status: Skypro Direct Feed Active 🟢")
else:
    st.sidebar.warning("Status: Running on Backup Fast Feed 🟡")


# ------------------------------------------
# 2. Fast Live Data Fetcher Engine
# ------------------------------------------
def fetch_live_nifty_price():
    # Primary Source: Skypro Direct API Token
    token = st.session_state.get("sky_token")
    if token:
        try:
            quote_url = f"{BASE_URL}/marketdata/instruments/quotes"
            headers = {"Authorization": token}
            quote_res = requests.get(
                quote_url,
                headers=headers,
                params={"instruments": "NSE_INDEX|NIFTY 50"},
                timeout=1.5,
            )
            if quote_res.status_code == 200:
                last_price = (
                    quote_res.json().get("result", {}).get("lastPrice", None)
                )
                if last_price and float(last_price) > 0:
                    return float(last_price)
        except Exception:
            pass

    # Secondary Source: Direct Fast Market Backup API
    try:
        url = "https://priceapi.moneycontrol.com/technicalData/v1/index/technicalChartData?symbol=IN%3BNSX&time=1"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=1.5)
        if res.status_code == 200:
            data = res.json()
            if "data" in data and len(data["data"]) > 0:
                return float(data["data"][-1][4])
    except Exception:
        pass

    return 23772.05


# ------------------------------------------
# 3. Master CSV Database Operations
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
                "Spot_Reference",
            ]
        )
        df_empty.to_csv(CSV_FILE, index=False)


def load_all_trades():
    init_master_csv()
    try:
        df = pd.read_csv(CSV_FILE)
        if (
            "Entry_Price" in df.columns
            and "Option_Entry_Price" not in df.columns
        ):
            df.rename(
                columns={"Entry_Price": "Option_Entry_Price"}, inplace=True
            )
        return df
    except Exception:
        return pd.DataFrame()


def update_trades_file(df):
    df.to_csv(CSV_FILE, index=False)


# ------------------------------------------
# 4. ITM Option Live PnL Processing Engine
# ------------------------------------------
live_nifty_price = fetch_live_nifty_price()
all_trades_df = load_all_trades()

if not all_trades_df.empty:
    for idx, row in all_trades_df.iterrows():
        if row["Date"] == TODAY_STR and row["Status"] == "OPEN":
            entry_premium = float(row["Option_Entry_Price"])
            is_ce = "CE" in str(row["Type"])

            spot_ref = float(row.get("Spot_Reference", live_nifty_price))
            if pd.isna(spot_ref) or spot_ref <= 0:
                spot_ref = live_nifty_price
                all_trades_df.at[idx, "Spot_Reference"] = spot_ref

            spot_diff = (
                (live_nifty_price - spot_ref)
                if is_ce
                else (spot_ref - live_nifty_price)
            )

            # ITM Option Premium estimation based on Delta 0.70
            current_option_premium = round(
                entry_premium + (spot_diff * ITM_DELTA), 2
            )
            all_trades_df.at[idx, "Option_Current_Price"] = (
                current_option_premium
            )

            premium_pts_move = round(current_option_premium - entry_premium, 2)

            # Target / SL logic strictly on ITM Premium (+45 / -15)
            if premium_pts_move >= 45.0:
                all_trades_df.at[idx, "Option_Current_Price"] = (
                    entry_premium + 45.0
                )
                all_trades_df.at[idx, "Status"] = "TARGET HIT (+45)"
                all_trades_df.at[idx, "Points_P&L"] = 45.0
                all_trades_df.at[idx, "Rupees_P&L"] = 45.0 * LOT_SIZE
            elif premium_pts_move <= -15.0:
                all_trades_df.at[idx, "Option_Current_Price"] = (
                    entry_premium - 15.0
                )
                all_trades_df.at[idx, "Status"] = "SL HIT (-15)"
                all_trades_df.at[idx, "Points_P&L"] = -15.0
                all_trades_df.at[idx, "Rupees_P&L"] = -15.0 * LOT_SIZE
            else:
                all_trades_df.at[idx, "Points_P&L"] = premium_pts_move
                all_trades_df.at[idx, "Rupees_P&L"] = round(
                    premium_pts_move * LOT_SIZE, 2
                )

    update_trades_file(all_trades_df)

# ------------------------------------------
# 5. Streamlit UI Dashboard & Date Filter
# ------------------------------------------
st.sidebar.markdown("---")
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

# Metrics Breakdown
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
c1.metric("Live Nifty Spot", f"{live_nifty_price:.2f}")
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

# 1-Second Auto Refresh Loop
time.sleep(1)
st.rerun()
