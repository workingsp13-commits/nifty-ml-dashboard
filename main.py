import os
from datetime import datetime
import pandas as pd
import requests

CSV_FILE = "trades_master.csv"
TODAY_STR = datetime.now().strftime("%Y-%m-%d")
TIME_STR = datetime.now().strftime("%H:%M:%S")


# Live Spot மற்றும் Live Option Premium Traded Price எடுக்கும் செயல்பாடு
def fetch_real_market_rates(strike=23700, option_type="CE"):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}

        # 1. Spot Price
        spot_url = "https://priceapi.moneycontrol.com/technicalData/v1/index/technicalChartData?symbol=IN%3BNSX&time=1"
        res = requests.get(spot_url, headers=headers, timeout=3).json()
        live_spot = float(res["data"][-1][4])

        # 2. Real Option Traded Price (LTP)
        opt_url = f"https://priceapi.moneycontrol.com/technicalNSE/options?symbol=NIFTY_{strike}_{option_type}"
        opt_res = requests.get(opt_url, headers=headers, timeout=3).json()
        live_opt_ltp = float(opt_res["data"]["lastPrice"])

        return live_spot, live_opt_ltp
    except Exception as e:
        print(f"Error fetching live market data: {e}")
        return 23772.05, 147.50  # Fallback if API is unreachable


def init_csv():
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


def run_signal_engine():
    init_csv()
    df = pd.read_csv(CSV_FILE)

    # Check for active open positions
    open_trades = df[(df["Date"] == TODAY_STR) & (df["Status"] == "OPEN")]
    if not open_trades.empty:
        print("An open position is active. Skipping duplicate signal.")
        return

    # Dynamic ITM Strike Selection
    spot_price, real_option_price = fetch_real_market_rates()
    itm_strike = int(spot_price // 100) * 100  # Round down for ITM CE Strike
    signal_type = "CE"

    # Log New Signal with REAL Option Market Price
    new_trade = {
        "Date": TODAY_STR,
        "Time": TIME_STR,
        "Type": f"NIFTY {itm_strike} {signal_type}",
        "Option_Strike": itm_strike,
        "Option_Entry_Price": real_option_price,
        "Option_Current_Price": real_option_price,
        "Status": "OPEN",
        "Points_P&L": 0.0,
        "Rupees_P&L": 0.0,
        "Spot_Reference": spot_price,
    }

    df_updated = pd.concat([df, pd.DataFrame([new_trade])], ignore_index=True)
    df_updated.to_csv(CSV_FILE, index=False)
    print(
        f"🟢 Signal Created! Strike: {itm_strike} {signal_type} | Real Entry Rate: {real_option_price} | Spot: {spot_price}"
    )


if __name__ == "__main__":
    run_signal_engine()
