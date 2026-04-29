import ccxt 
import pandas as pd
import time
import requests
import math
from datetime import datetime, timedelta

# ================= TELEGRAM =================
TELEGRAM_BOT_TOKEN = "8771824533:AAGmnaadlJ_W4gzmXBXlqbB0YtLWePUEBC8"
CHAT_ID = "1868312878"

def send_workspace(message):
    try:
        print(message, flush=True)
        with open("workspace_logs.txt", "a", encoding="utf-8") as f:
            f.write(message + "\n" + "-"*60 + "\n")
    except Exception as e:
        print("Workspace error:", e)

def send_telegram(message):
    message = "5mpro59\n" + message
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print("Telegram error:", e, flush=True)

# ================= BINANCE =================
exchange = ccxt.binance({
    'enable_rate_limit': True,
    'options': {'defaultType': 'future'}
})

# ================= GLOBAL =================
active_trades = []
total_trades = 0
win_trades = 0

last_candle_time = {}
last_signal_time = {}

symbols = []
last_symbol_update = 0

# ================= SYMBOL =================
def update_symbols():
    global symbols
    try:
        markets = exchange.fetch_markets()
        tickers = exchange.fetch_tickers()

        candidates = []

        for m in markets:
            if not m.get('contract'):
                continue
            if m.get('quote') != 'USDT':
                continue

            symbol = m['symbol']
            if symbol not in tickers:
                continue

            t = tickers[symbol]
            vol = t.get('quoteVolume') or 0
            pct = abs(t.get('percentage') or 0)

            if vol == 0:
                continue

            score = math.log(vol + 1) * 0.6 + pct * 0.4
            candidates.append({"symbol": symbol, "score": score})

        candidates = sorted(candidates, key=lambda x: x["score"], reverse=True)
        symbols = [c["symbol"] for c in candidates[:50]]

        print(f"🔥 Symbols updated: {len(symbols)}")

    except Exception as e:
        print("Symbol update error:", e)

# ================= RESULT TRACKER =================
def check_trade_results():
    global active_trades, total_trades, win_trades

    for trade in active_trades[:]:
        try:
            ticker = exchange.fetch_ticker(trade["symbol"])
            price = ticker["last"]

            if trade["type"] == "LONG":
                if price >= trade["tp"]:
                    result = "WIN"
                elif price <= trade["sl"]:
                    result = "LOSS"
                else:
                    continue
            else:
                if price <= trade["tp"]:
                    result = "WIN"
                elif price >= trade["sl"]:
                    result = "LOSS"
                else:
                    continue

            total_trades += 1
            if result == "WIN":
                win_trades += 1

            winrate = (win_trades / total_trades) * 100 if total_trades > 0 else 0

            color_icon = "🔵" if result == "WIN" else "🟠"

            msg = (
                f"{color_icon} RESULT SIGNAL\n"
                f"{trade['symbol']}\n"
                f"Type: {trade['type']}\n"
                f"Result: {result}\n\n"
                f"Entry: {trade['entry']:.6f}\n"
                f"Exit: {price:.6f}\n"
                f"TP: {trade['tp']:.6f}\n"
                f"SL: {trade['sl']:.6f}\n\n"
                f"Winrate: {win_trades}/{total_trades} ({winrate:.2f}%)"
            )

            send_telegram(msg)
            send_workspace(msg)

            active_trades.remove(trade)

        except Exception as e:
            print("Result check error:", e)

# ================= ICT SCORE ENGINE =================
def ict_score_engine(df, df1h, df15m, signal):

    last = df.iloc[-2]
    prev = df.iloc[-3]
    prev2 = df.iloc[-4]
    price = last['close']
    tol = price * 0.002

    sweep_low = last['low'] < min(prev['low'], prev2['low'])
    sweep_high = last['high'] > max(prev['high'], prev2['high'])

    bos_up = last['close'] > prev['high']
    bos_down = last['close'] < prev['low']

    structure_long = sweep_low and bos_up
    structure_short = sweep_high and bos_down

    h = df1h.iloc[-2]
    pivot = (h['high'] + h['low'] + h['close']) / 3

    pivot_long = abs(price - pivot) < tol
    pivot_short = abs(price - pivot) < tol

    high = df['high'].rolling(20).max().iloc[-2]
    low = df['low'].rolling(20).min().iloc[-2]

    fib_618 = low + (high - low) * 0.618
    fib_5 = low + (high - low) * 0.5

    fibo_long = abs(price - fib_618) < tol or abs(price - fib_5) < tol
    fibo_short = fibo_long

    m = df15m.iloc[-2]
    p = df15m.iloc[-3]

    bullish_fvg = p['high'] < m['low']
    bearish_fvg = p['low'] > m['high']

    ftr_long = last['low'] <= prev['high']
    ftr_short = last['high'] >= prev['low']

    fvg_ftr_long = bullish_fvg or ftr_long
    fvg_ftr_short = bearish_fvg or ftr_short

    bullish_engulf = (m['close'] > m['open'] and p['close'] < p['open'])
    bearish_engulf = (m['close'] < m['open'] and p['close'] > p['open'])

    score = 0
    features = 0
    log = []

    def add(cond, name, pts):
        nonlocal score, features
        if cond:
            score += pts
            features += 1
            log.append(f"{name} ✔ +{pts}")
        else:
            log.append(f"{name} ❌")

    if signal == "LONG":
        add(structure_long, "STRUCTURE", 40)
        add(pivot_long, "PIVOT", 15)
        add(fibo_long, "FIBO", 20)
        add(fvg_ftr_long, "FVG/FTR", 20)
        add(bullish_engulf, "ENGULF", 30)
    else:
        add(structure_short, "STRUCTURE", 40)
        add(pivot_short, "PIVOT", 15)
        add(fibo_short, "FIBO", 20)
        add(fvg_ftr_short, "FVG/FTR", 20)
        add(bearish_engulf, "ENGULF", 30)

    if features >= 3:
        return True, score, log

    return False, score, log

# ================= INDICATORS =================
def calculate_adx(df, period=14, smoothing=20):
    df = df.copy()
    df['prev_close'] = df['close'].shift(1)

    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['prev_close']).abs(),
        (df['low'] - df['prev_close']).abs()
    ], axis=1).max(axis=1)

    up = df['high'].diff()
    down = -df['low'].diff()

    plus_dm = ((up > down) & (up > 0)) * up
    minus_dm = ((down > up) & (down > 0)) * down

    tr_s = tr.ewm(alpha=1/period).mean()
    plus_s = plus_dm.ewm(alpha=1/period).mean()
    minus_s = minus_dm.ewm(alpha=1/period).mean()

    plus_di = 100 * (plus_s / tr_s)
    minus_di = 100 * (minus_s / tr_s)

    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100
    df['adx'] = dx.ewm(alpha=1/smoothing).mean()
    return df

def calculate_wavetrend(df):
    hlc3 = (df['high'] + df['low'] + df['close']) / 3
    esa = hlc3.ewm(span=7).mean()
    d = (hlc3 - esa).abs().ewm(span=7).mean()
    ci = (hlc3 - esa) / (0.015 * d)
    wt1 = ci.ewm(span=10).mean()
    wt2 = wt1.rolling(4).mean()
    df['wt1'] = wt1
    df['wt2'] = wt2
    return df

def calculate_smi(df):
    hh = df['high'].rolling(14).max()
    ll = df['low'].rolling(14).min()
    m = (hh + ll) / 2
    d = df['close'] - m
    hl_range = (hh - ll).replace(0, 1)

    smi_raw = (d / (hl_range / 2)) * 100
    smi_k = smi_raw.ewm(span=3).mean()
    smi_d = smi_k.ewm(span=3).mean()

    df['smi'] = smi_k
    df['smi_signal'] = smi_d
    return df

def calculate_vwap(df):
    tp = (df['high'] + df['low'] + df['close']) / 3
    df['vwap'] = (tp * df['volume']).cumsum() / df['volume'].cumsum()
    return df

def calculate_atr(df):
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low'] - df['close'].shift(1)).abs()
    ], axis=1).max(axis=1)

    df['atr'] = tr.rolling(14).mean()
    return df

def compute_indicators(df):
    df['ema_fast'] = df['close'].ewm(span=21).mean()
    df['ema_slow'] = df['close'].ewm(span=50).mean()

    df = calculate_adx(df)
    df = calculate_wavetrend(df)
    df = calculate_smi(df)
    df = calculate_vwap(df)
    df = calculate_atr(df)

    df['bb_mid'] = df['close'].rolling(20).mean()
    return df

# ================= SIGNAL =================
def check_signal(df, rsi_1h, rsi_5m):
    last = df.iloc[-2]

    price = last['close']
    adx = last['adx']
    ema_fast = last['ema_fast']
    ema_slow = last['ema_slow']
    smi = last['smi']
    wt1 = last['wt1']
    wt2 = last['wt2']
    bb_mid = last['bb_mid']
    vwap = last['vwap']

    if adx < 18:
        return None

    def add(cond, text, pts, details, score):
        if cond:
            score += pts
            details.append(f"{text} ✔ (+{pts})")
        else:
            details.append(f"{text} ❌ (+0)")
        return score

    details = []
    score = 0

    score = add(ema_fast > ema_slow, "EMA UP", 20, details, score)
    score = add(price > vwap, "VWAP", 20, details, score)
    score = add(smi < 0 and wt1 > wt2, "SMI+WT", 25, details, score)
    score = add(price > bb_mid, "BB", 10, details, score)
    score = add(rsi_1h > 52, "RSI 1H", 25, details, score)
    score = add(rsi_5m > 55, "RSI 5M", 10, details, score)

    if ema_fast > ema_slow and score >= 80:
        return "LONG", score, details

    details = []
    score = 0

    score = add(ema_fast < ema_slow, "EMA DOWN", 20, details, score)
    score = add(price < vwap, "VWAP", 20, details, score)
    score = add(smi > 0 and wt1 < wt2, "SMI+WT", 25, details, score)
    score = add(price < bb_mid, "BB", 10, details, score)
    score = add(rsi_1h < 48, "RSI 1H", 25, details, score)
    score = add(rsi_5m < 45, "RSI 5M", 10, details, score)

    if ema_fast < ema_slow and score >= 80:
        return "SHORT", score, details

    return None

# ================= MAIN =================
print("🚀 5mpro59 started...", flush=True)

while True:
    now = time.time()

    check_trade_results()

    if now - last_symbol_update > 3600 or len(symbols) == 0:
        update_symbols()
        last_symbol_update = now

    for symbol in symbols:
        try:
            if symbol in last_signal_time and now - last_signal_time[symbol] < 3600:
                continue

            df = pd.DataFrame(exchange.fetch_ohlcv(symbol, '5m', limit=100),
                              columns=['time','open','high','low','close','volume'])
            df = compute_indicators(df)

            df1h = pd.DataFrame(exchange.fetch_ohlcv(symbol, '1h', limit=100),
                                columns=['time','open','high','low','close','volume'])

            df15m = pd.DataFrame(exchange.fetch_ohlcv(symbol, '15m', limit=100),
                                 columns=['time','open','high','low','close','volume'])

            delta = df1h['close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = -delta.where(delta < 0, 0).rolling(14).mean()
            rs = gain / loss
            rsi_1h = (100 - (100/(1+rs))).iloc[-1]

            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = -delta.where(delta < 0, 0).rolling(14).mean()
            rs = gain / loss
            rsi_5m = (100 - (100/(1+rs))).iloc[-1]

            result = check_signal(df, rsi_1h, rsi_5m)

            if result:
                signal, score, details = result

                ok, ict_score, ict_log = ict_score_engine(df, df1h, df15m, signal)

                if not ok:
                    continue

                entry = df.iloc[-2]['close']
                atr = df.iloc[-2]['atr']
                atr_pct = atr / entry if entry != 0 else 0

                if signal == "LONG":
                    tp = entry * (1 + atr_pct * 1.2)
                    sl = entry * (1 - atr_pct)
                    signal_text = "🟢 LONG"
                else:
                    tp = entry * (1 - atr_pct * 1.2)
                    sl = entry * (1 + atr_pct)
                    signal_text = "🔴 SHORT"

                tr_time = datetime.utcfromtimestamp(now) + timedelta(hours=3)

                msg = (
                    f"{symbol}\n"
                    f"{signal_text}\n"
                    f"Score: {score}\nICT Score: {ict_score}\n\n"
                    f"Time (TR): {tr_time.strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"Entry: {entry:.6f}\nTP: {tp:.6f}\nSL: {sl:.6f}\n\n"
                    + "\n".join(details)
                    + "\n\nICT:\n" + "\n".join(ict_log)
                )

                send_telegram(msg)
                send_workspace("5mpro59 ENTRY SIGNAL\n" + msg)

                last_signal_time[symbol] = now

                active_trades.append({
                    "symbol": symbol,
                    "type": signal,
                    "entry": entry,
                    "tp": tp,
                    "sl": sl,
                    "open_time": now
                })

            time.sleep(10)

        except Exception as e:
            print(symbol, "error:", e)