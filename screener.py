import os
import sys
import html
import requests
import datetime
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_date_window(days=30):
    """Returns (today_date, end_date) for a lookahead window."""
    today = datetime.date.today()
    end_date = today + datetime.timedelta(days=days)
    return today, end_date

def parse_date(date_val):
    """Safely parses strings, ints, or timestamps into a datetime.date object."""
    if not date_val:
        return None
    try:
        if isinstance(date_val, (int, float)):
            return datetime.date.fromtimestamp(date_val)
        if isinstance(date_val, str):
            clean_str = date_val.split('T')[0].split(' ')[0]
            return datetime.datetime.strptime(clean_str, '%Y-%m-%d').date()
    except Exception:
        pass
    return None

def check_tsx_ticker(sym, start_date, end_date):
    """Worker function to safely check a TSX ticker's yield and ex-date."""
    try:
        formatted_sym = sym if sym.endswith('.TO') else f"{sym}.TO"
        tk = yf.Ticker(formatted_sym)
        
        info = {}
        try:
            info = tk.info or {}
        except Exception:
            pass

        ex_dt = parse_date(info.get('exDividendDate'))
        if not ex_dt or not (start_date <= ex_dt <= end_date):
            return None

        raw_yield = info.get('dividendYield')
        if raw_yield is None:
            div_yield_pct = 0.0
        else:
            try:
                div_yield = float(raw_yield)
                div_yield_pct = div_yield * 100 if div_yield < 0.20 else div_yield
            except (ValueError, TypeError):
                div_yield_pct = 0.0

        raw_price = info.get('regularMarketPrice') or info.get('currentPrice') or info.get('previousClose') or 0.0
        try:
            price = float(raw_price)
        except (ValueError, TypeError):
            price = 0.0

        currency = str(info.get('currency', 'CAD')).upper()

        if div_yield_pct > 0:
            return {
                'symbol': formatted_sym,
                'ex_date': str(ex_dt),
                'yield': div_yield_pct,
                'price': price,
                'currency': currency
            }
    except Exception as e:
        print(f"Error checking {sym}: {e}")
    return None

def fetch_tsx_ex_dividend_stocks(fmp_key, target_count=50):
    """Find TSX stocks going ex-dividend in the next 30 days."""
    start_date, end_date = get_date_window(days=30)
    print(f"--> Screening TSX Ex-Dividend window: {start_date} to {end_date}")

    candidate_symbols = set()

    if fmp_key:
        print("--> Querying Financial Modeling Prep Dividend Calendar...")
        fmp_url = f"https://financialmodelingprep.com/api/v3/stock_dividend_calendar?from={start_date}&to={end_date}&apikey={fmp_key}"
        try:
            res = requests.get(fmp_url, timeout=15)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list):
                    for item in data:
                        sym = str(item.get('symbol', '')).strip().upper()
                        if sym.endswith('.TO'):
                            candidate_symbols.add(sym)
        except Exception as e:
            print(f"FMP Request Exception: {e}")

    tsx_pool = [
        "ENB", "TRP", "PPL", "KEY", "GEI", "ALA", "CVE", "SU", "CNQ", "IMO",
        "BNS", "CM", "TD", "RY", "BMO", "NA", "CWB", "LB", "FN", "BTK",
        "BCE", "T", "RCI.B", "QBR.B", "AQN", "EMA", "FTS", "CU", "H", "NPI",
        "POW", "SLF", "MFC", "IGM", "GWO", "EIF", "DIR-UN", "CHP-UN", "REI-UN",
        "GRT-UN", "HR-UN", "AP-UN", "CAR-UN", "SRU-UN", "CRR-UN", "NWH-UN", "SGR-UN",
        "TNT-UN", "KMP-UN", "DRG-UN", "BTB-UN", "PRV-UN", "XTC", "NGL", "NFI",
        "TIH", "ARE", "BDT", "BEP-UN", "BIP-UN", "CPX", "TA", "RNW", "DR", 
        "DIV", "CHE-UN", "DGS", "DFN", "FTN", "FFN", "LBS", "GDV", "TXF", 
        "BK", "PDN", "SBN", "PAY", "PWI", "ENS"
    ]

    for sym in tsx_pool:
        clean_sym = sym if sym.endswith('.TO') else f"{sym}.TO"
        candidate_symbols.add(clean_sym)

    print(f"--> Multi-threading yield checks for {len(candidate_symbols)} TS
