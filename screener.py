import os
import sys
import html
import requests
import datetime
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_date_window(days=60):
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
    """Worker function to check a TSX ticker's yield and status."""
    try:
        formatted_sym = sym if sym.endswith('.TO') else sym + ".TO"
        tk = yf.Ticker(formatted_sym)
        
        info = {}
        try:
            info = tk.info or {}
        except Exception:
            pass

        ex_dt = parse_date(info.get('exDividendDate'))
        
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
                'ex_date': str(ex_dt) if ex_dt else "TBD",
                'yield': div_yield_pct,
                'price': price,
                'currency': currency
            }
    except Exception as e:
        print("Error checking ticker:", sym, e)
    return None

def fetch_tsx_ex_dividend_stocks(fmp_key):
    """Find TSX stocks with active dividend yields."""
    start_date, end_date = get_date_window(days=60)
    print("--> Screening TSX Dividend Candidates from", start_date, "to", end_date)

    candidate_symbols = set()

    if fmp_key:
        fmp_url = "https://financialmodelingprep.com/api/v3/stock_dividend_calendar?from=" + str(start_date) + "&to=" + str(end_date) + "&apikey=" + fmp_key
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
            print("FMP Request Exception:", e)

    # Broadened pool of high-yield Canadian equities, REITs, and Split Corps
    tsx_pool = [
        "ENB", "TRP", "PPL", "KEY", "GEI", "ALA", "CVE", "SU", "CNQ", "IMO",
        "BNS", "CM", "TD", "RY", "BMO", "NA", "LB", "FN", "BCE", "T", 
        "RCI.B", "QBR.B", "AQN", "EMA", "FTS", "CU", "H", "NPI", "POW", 
        "SLF", "MFC", "IGM", "GWO", "EIF", "DIR-UN", "REI-UN", "GRT-UN", 
        "SRU-UN", "CAR-UN", "XTC", "NFI", "TIH", "ARE", "BDT", "CPX", "TA", 
        "RNW", "DIV", "CHE-UN", "DGS", "DFN", "FTN", "FFN", "LBS", "GDV", "TXF",
        "BK", "PDN", "SBN", "PAY", "PWI", "ENS", "TF", "FSZ", "FC", "AI",
        "BTB-UN", "MKP", "PZA", "CCA", "ENGH", "Y", "SGR-UN", "PRV-UN", "ADN",
        "FRU", "MFI", "LUG", "HR-UN", "WFC", "CSW-A", "PIF", "CJ", "PEY",
        "PXT", "CRR-UN", "CRT-UN", "MRD", "RSI", "LIF", "PLZ-UN", "CHP-UN"
    ]

    for sym in tsx_pool:
        clean_sym = sym if sym.endswith('.TO') else sym + ".TO"
        candidate_symbols.add(clean_sym)

    qualifying_stocks = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(check_tsx_ticker, sym, start_date, end_date)
            for sym in candidate_symbols
        ]
        for future in as_completed(futures):
            res = future.result()
            if res:
                qualifying_stocks.append(res)

    return qualifying_stocks

def send_telegram_msg(bot_token, chat_id, msg):
    """Sends plain text message to Telegram with automatic payload chunking."""
    tg_url = "https://api.telegram.org/bot" + bot_token + "/sendMessage"

    lines = msg.split('\n')
    chunks = []
    current_chunk = ""

    for line in lines:
        if len(current_chunk) + len(line) + 1 > 3500:
            chunks.append(current_chunk)
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"

    if current_chunk:
        chunks.append(current_chunk)

    for idx, chunk in enumerate(chunks, 1):
        payload = {'chat_id': chat_id, 'text': chunk}
        try:
            res = requests.post(tg_url, json=payload, timeout=10)
            print("Chunk Delivery Code:", res.status_code)
            if res.status_code != 200:
                print("Telegram API Error Payload:", res.text)
        except Exception as e:
            print("Telegram Post Exception:", e)

def main():
    fmp_key = os.environ.get('FMP_API_KEY', '').strip()
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

    print("=== TSX TOP 30 DIVIDEND SCREENER ===")

    if not bot_token or not chat_id:
        print("CRITICAL ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing.")
        sys.exit(1)

    raw_stocks = fetch_tsx_ex_dividend_stocks(fmp_key)
    start_date, end_date = get_date_window(days=60)

    if not raw_stocks:
        no_stocks_msg = "🇨🇦 TSX Dividend Report:\nNo matching dividend stocks returned."
        send_telegram_msg(bot_token, chat_id, no_stocks_msg)
        sys.exit(0)

    df = pd.DataFrame(raw_stocks)
    df = df.drop_duplicates(subset=['symbol'])
    
    # Strictly select the top 30 highest dividend yields
    df_sorted = df.sort_values(by='yield', ascending=False).head(30)

    formatted_rows = []
    for idx, row in enumerate(df_sorted.to_dict('records'), 1):
        sym_clean = html.escape(str(row['symbol']))
        ex_dt = str(row['ex_date'])
        yld = f"{float(row['yield']):.2f}"
        prc = f"{float(row['price']):.2f}"
        curr = str(row['currency'])
        
        row_str = str(idx) + ". " + sym_clean + " | Ex-Date: " + ex_dt + " | Yield: " + yld + "% | Price: $" + prc + " " + curr
        formatted_rows.append(row_str)

    header = "🇨🇦 Top 30 High Yield TSX Dividend Stocks\n" + str(start_date) + " to " + str(end_date) + "\n\n"
    msg_body = header + "\n".join(formatted_rows)

    send_telegram_msg(bot_token, chat_id, msg_body)

if __name__ == '__main__':
    try:
        main()
    except Exception as fatal_err:
        print("Caught Script Exception:", fatal_err)
        sys.exit(1)
