import os
from datetime import datetime
import pandas as pd
import requests

CSV_FILE = "trades_master.csv"
TODAY_STR = datetime.now().strftime("%Y-%m-%d")
TIME_STR = datetime.now().strftime("%H:%M:%S")


# 1. Fetch Real-time Nifty Spot Price
def fetch_nifty_spot():
    try:
        url = "https://priceapi.moneycontrol.com/technicalData/v1/index/technicalChartData?symbol=IN%3BNSX&time=1"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=3)
        if res.status_code == 200:
            data = res.json()
            if "data" in data and len(data["data"]) > 0:
                return float(data["data"][-1][4])
    except Exception as e:
        print(f"Error fetching live spot price: {e}")

    return 23772.05  # Backup fallback price


# 2. Check or Create Master CSV File
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


# 3. Simple Momentum / Signal Logic Engine
def generate_signal(spot_price):
    """Simple ML / Strategy Condition.

    Triggers a CE signal if Spot breaks resistance / shows momentum.
    """
    init_csv()
    df = pd.read_csv(CSV_FILE)

    # Prevent duplicate active open trades for today
    today_trades = df[(df["Date"] == TODAY_STR) & (df["Status"] == "OPEN")]
    if not today_trades.empty:
        print(
            "An open position is already active. Skipping new signal generation."
        )
        return

    # ITM Option Strike Selection Logic (e.g., Round Spot down to nearest 100 for ITM CE)
    itm_strike = int(spot_price // 100) * 100
    estimated_itm_premium = round(
        (spot_price - itm_strike) + 120.0, 2
    )  # Intrinsic + Time Value Estimation

    # Example Signal Trigger Condition (Can be replaced with ML model .predict())
    signal_type = "CE"  # Buy ITM Call Option

    new_trade = {
        "Date": TODAY_STR,
        "Time": TIME_STR,
        "Type": f"NIFTY {itm_strike} {signal_type}",
        "Option_Strike": itm_strike,
        "Option_Entry_Price": estimated_itm_premium,
        "Option_Current_Price": estimated_itm_premium,
        "Status": "OPEN",
        "Points_P&L": 0.0,
        "Rupees_P&L": 0.0,
        "Spot_Reference": spot_price,
    }

    # Append new trade record
    df_updated = pd.concat([df, pd.DataFrame([new_trade])], ignore_index=True)
    df_updated.to_csv(CSV_FILE, index=False)
    print(
        f"🟢 New Signal Generated & Logged: {signal_type} at Spot {spot_price} (Premium: {estimated_itm_premium})"
    )


if __name__ == "__main__":
    spot = fetch_nifty_spot()
    print(f"Current Nifty Spot Price: {spot}")
    generate_signal(spot)
