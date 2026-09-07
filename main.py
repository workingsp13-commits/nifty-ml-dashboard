import requests

def get_live_market_data(strike=23700, option_type="CE", expiry="2026-09-10"):
    """
    NSE / Moneycontrol Feed-இல் இருந்து Spot Price மற்றும் 
    Option Contract-ன் நேரடி Traded LTP-ஐ எடுக்கும் செயல்பாடு.
    """
    try:
        # 1. Spot Price Fetch
        spot_url = "https://priceapi.moneycontrol.com/technicalNSE/indexMaster?symbol=NIFTY"
        spot_res = requests.get(spot_url, timeout=5).json()
        live_spot = float(spot_res['data']['lastPrice'])
        
        # 2. Live Option Contract LTP Fetch
        # Option Symbol Format for API (e.g., NIFTY26SEP23700CE)
        option_symbol = f"NIFTY_{expiry}_{strike}_{option_type}"
        opt_url = f"https://priceapi.moneycontrol.com/technicalNSE/options?symbol={option_symbol}"
        
        opt_res = requests.get(opt_url, timeout=5).json()
        live_option_ltp = float(opt_res['data']['lastPrice'])
        
        return live_spot, live_option_ltp
    except Exception as e:
        # API கனெக்ஷன் கிடைக்காத பட்சத்தில் பழைய மதிப்பை அப்படியே திருப்பியனுப்பும் Safety Fallback
        return None, None
