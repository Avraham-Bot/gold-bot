import pandas as pd
import requests
import ta
import numpy as np
from datetime import datetime, timedelta
import os
import warnings
warnings.filterwarnings('ignore')

# קבל את הנתונים מהסביבה (בטוח יותר)
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

# הוסף סימבולים יציבים יותר ל-Yahoo Finance
DEFAULT_SYMBOLS = ['GC=F', 'GLD', 'IAU', 'GOLD', 'XAUUSD=X']


def send_telegram_message(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message}
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            print(f"✅ Message sent at {datetime.now().strftime('%H:%M:%S')}")
        else:
            print(f"❌ Failed: {response.status_code}")
    except Exception as e:
        print(f"Error: {e}")


def fetch_yahoo_fast(symbol, interval="1h", period_days=60):
    end = int(datetime.utcnow().timestamp())
    start = int((datetime.utcnow() - timedelta(days=period_days)).timestamp())

    url = (
        f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?symbol={symbol}&period1={start}&period2={end}&interval={interval}"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json"
    }

    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"❌ Error fetching {symbol}: {e}")
        return pd.DataFrame()

    if 'chart' not in data or data['chart']['result'] is None:
        return pd.DataFrame()

    result = data['chart']['result'][0]
    timestamps = result['timestamp']
    indicators = result['indicators']['quote'][0]

    df = pd.DataFrame({
        "Date": pd.to_datetime(timestamps, unit='s'),
        "Open": indicators['open'],
        "High": indicators['high'],
        "Low": indicators['low'],
        "Close": indicators['close'],
        "Volume": indicators['volume'],
    })

    df.set_index('Date', inplace=True)
    return df.dropna()


def calculate_indicators(data):
    data['SMA20'] = ta.trend.sma_indicator(data['Close'], window=20)
    data['SMA50'] = ta.trend.sma_indicator(data['Close'], window=50)
    data['EMA20'] = ta.trend.ema_indicator(data['Close'], window=20)
    data['RSI'] = ta.momentum.rsi(data['Close'], window=14)
    macd = ta.trend.MACD(data['Close'])
    data['MACD'] = macd.macd_diff()
    bb = ta.volatility.BollingerBands(data['Close'])
    data['BB_Upper'] = bb.bollinger_hband()
    data['BB_Lower'] = bb.bollinger_lband()
    data['ATR'] = ta.volatility.average_true_range(data['High'], data['Low'], data['Close'], window=14)
    return data


def generate_signal(data):
    latest = data.iloc[-1]
    buy_score = 0
    if latest['SMA20'] > latest['SMA50']: buy_score += 2
    if 30 < latest['RSI'] < 70: buy_score += 1
    if latest['MACD'] > 0: buy_score += 1
    if latest['Close'] > latest['EMA20']: buy_score += 1
    if latest['Close'] < latest['BB_Upper']: buy_score += 1

    sell_score = 0
    if latest['SMA20'] < latest['SMA50']: sell_score += 2
    if latest['RSI'] > 70 or latest['RSI'] < 30: sell_score += 1
    if latest['MACD'] < 0: sell_score += 1
    if latest['Close'] < latest['EMA20']: sell_score += 1
    if latest['Close'] > latest['BB_Lower']: sell_score += 1

    if buy_score >= 4: return 'BUY', buy_score
    elif sell_score >= 4: return 'SELL', sell_score
    else: return 'HOLD', max(buy_score, sell_score)


def calculate_sl_tp(data, signal):
    latest = data.iloc[-1]
    atr = latest['ATR']
    price = latest['Close']
    if signal == 'BUY': return price - (atr * 1.5), price + (atr * 3)
    elif signal == 'SELL': return price + (atr * 1.5), price - (atr * 3)
    else: return None, None


def run_bot():
    print("\n" + "="*50)
    print(f"🤖 Gold Bot Running at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*50)

    data = None
    used_symbol = None

    for symbol in DEFAULT_SYMBOLS:
        data = fetch_yahoo_fast(symbol, interval="1h", period_days=60)
        if not data.empty and len(data) > 50:
            used_symbol = symbol
            print(f"✅ Success with {symbol}")
            break

    if data is None or data.empty:
        message = "⚠️ Unable to fetch gold data from any source"
        print(message)
        send_telegram_message(message)
        return

    print(f"📈 Data loaded: {len(data)} candles")

    try:
        data = calculate_indicators(data)
        data = data.dropna()
        print(f"📊 Indicators calculated successfully")
    except Exception as e:
        print(f"❌ Error calculating indicators: {e}")
        return

    signal, score = generate_signal(data)
    latest = data.iloc[-1]
    price = float(latest['Close'])
    rsi = float(latest['RSI'])

    print(f"\n📊 Analysis Results:")
    print(f"   Symbol: {used_symbol}")
    print(f"   Price: ${price:.2f}")
    print(f"   RSI: {rsi:.1f}")
    print(f"   Signal: {signal} (Score: {score}/6)")

    if signal != 'HOLD':
        stop_loss, take_profit = calculate_sl_tp(data, signal)
        risk = abs(price - stop_loss)
        reward = abs(take_profit - price)
        risk_reward_ratio = reward / risk if risk > 0 else 0
        message = f"""
🏆 **GOLD SIGNAL ALERT** 🏆

📍 Signal: **{signal}**
💰 Price: ${price:.2f}
📊 Symbol: {used_symbol}

🎯 Take Profit: ${take_profit:.2f} (+${reward:.2f})
🛑 Stop Loss: ${stop_loss:.2f} (-${risk:.2f})
📈 Risk/Reward: 1:{risk_reward_ratio:.1f}

📊 **Indicators:**
- RSI: {rsi:.1f}
- SMA20: ${latest['SMA20']:.2f}
- SMA50: ${latest['SMA50']:.2f}
- MACD: {latest['MACD']:.2f}

💡 Signal Strength: {score}/6
⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC

⚠️ This is not financial advice. Trade at your own risk!
"""
        send_telegram_message(message)
        print(f"\n✅ Signal sent to Telegram!")
    else:
        print(f"ℹ️ No signal at this time (HOLD)")
        hour = datetime.now().hour
        if hour % 6 == 0:
            status_msg = f"""
📊 Gold Status Update

Symbol: {used_symbol}
Price: ${price:.2f}
RSI: {rsi:.1f}
Trend: {'🟢 Bullish' if latest['SMA20'] > latest['SMA50'] else '🔴 Bearish'}
Signal: No action needed

Next check in 30 minutes...
"""
            send_telegram_message(status_msg)
            print("📨 Status update sent")

    print("\n✅ Bot run completed successfully!")


if __name__ == "__main__":
    run_bot()
