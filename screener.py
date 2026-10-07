import os
import sys
import html
import requests
import datetime
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_date_window(days=45):
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

        # Check if ex_date is in range OR return high-yield dividend stock as fallback
        in_range = bool(ex_dt and (start_date <= ex_dt <= end_date))
        
        if div_yield_pct > 0 and (in_range or ex_dt is None):
            return {
                'symbol': formatted_sym,
                'ex_date': str(ex_dt) if ex_dt else "TBD",
                'yield': div_yield_pct,
                'price': price,
                'currency': currency,
                'in_range': in_range
            }
    except Exception as e:
        print("Error checking ticker:", sym, e)
    return None

def fetch_tsx_ex_dividend_stocks(fmp_key):
    """Find TSX stocks going ex-dividend."""
    start_date, end_date = get_date_window(days=45)
    print("--> Screening TSX Ex-Dividend window:", start_date, "to", end_date)

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

    tsx_pool = [
        "ENB", "TRP", "PPL", "KEY", "GEI", "ALA", "CVE", "SU", "CNQ", "IMO",
        "BNS", "CM", "TD", "RY", "BMO", "NA", "LB", "FN", "BCE", "T", 
        "RCI.B", "QBR.B", "AQN", "EMA", "FTS", "CU", "H", "NPI", "POW", 
        "SLF", "MFC", "IGM", "GWO", "EIF", "DIR-UN", "REI-UN", "GRT-UN", 
        "SRU-UN", "CAR-UN", "XTC", "NFI", "TIH", "ARE", "BDT", "CPX", "TA", 
        "RNW", "DIV", "CHE-UN", "DGS", "DFN", "FTN", "FFN", "LBS", "GDV", "TXF"
    ]

    for sym in tsx_pool:
        clean_sym = sym if sym.endswith('.TO') else sym + ".TO"
        candidate_symbols.add(clean_sym)

    qualifying_stocks = []
    with ThreadPoolExecutor(max_workers=8) as executor:
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
            print("Telegram API Status Code:", res.status_code)
            if res.status_code != 200:
                print("Telegram API Error Response:", res.text)
        except Exception as e:
            print("Telegram Exception:", e)

def main():
    fmp_key = os.environ.get('FMP_API_KEY', '').strip()
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

    print("=== TSX EX-DIVIDEND SCREENER ===")

    if not bot_token or not chat_id:
        print("CRITICAL ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing in environment variables.")
        sys.exit(1)

    raw_stocks = fetch_tsx_ex_dividend_stocks(fmp_key)
    start_date, end_date = get_date_window(days=45)

    if not raw_stocks:
        no_stocks_msg = "🇨🇦 TSX Ex-Dividend Report (" + str(start_date) + " to " + str(end_date) + "):\nNo matching dividend stocks returned from feed."
        send_telegram_msg(bot_token, chat_id, no_stocks_msg)
        sys.exit(0)

    df = pd.DataFrame(raw_stocks)
    df = df.drop_duplicates(subset=['symbol'])
    df_sorted = df.sort_values(by='yield', ascending=False).head(50)

    formatted_rows = []
    for idx, row in enumerate(df_sorted.to_dict('records'), 1):
        sym_clean = html.escape(str(row['symbol']))
        ex_dt = str(row['ex_date'])
        yld = f"{float(row['yield']):.2f}"
        prc = f"{float(row['price']):.2f}"
        curr = str(row['currency'])
        
        row_str = str(idx) + ". " + sym_clean + " | Ex-Date: " + ex_dt + " | Yield: " + yld + "% | Price: $" + prc + " " + curr
        formatted_rows.append(row_str)

    header = "🇨🇦 TSX Ex-Dividend Calendar Watchlist\nTop Dividend Yielding Canadian Stocks\n\n"
    msg_body = header + "\n".join(formatted_rows)

    send_telegram_msg(bot_token, chat_id, msg_body)

if __name__ == '__main__':
    try:
        main()
    except Exception as fatal_err:
        print("Caught Script Exception:", fatal_err)
        sys.exit(1)
