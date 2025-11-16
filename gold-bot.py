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


def fetch_yahoo_fast(symbol, interval="1h", period_days=90):
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
    # אינדיקטורים בלבד
    data['SMA50'] = ta.trend.sma_indicator(data['Close'], window=50)
    data['SMA200'] = ta.trend.sma_indicator(data['Close'], window=200)
    data['EMA20'] = ta.trend.ema_indicator(data['Close'], window=20)
    data['RSI'] = ta.momentum.rsi(data['Close'], window=14)
    data['MACD'] = ta.trend.macd_diff(data['Close'])
    data['ATR'] = ta.volatility.average_true_range(data['High'], data['Low'], data['Close'], window=14)
    
    # VWAP
    data['VWAP'] = ta.volume.volume_weighted_average_price(
        high=data['High'],
        low=data['Low'],
        close=data['Close'],
        volume=data['Volume']
    )
    
    # Price Action Patterns
    # Engulfing
    data['Engulf'] = None
    for i in range(1, len(data)):
        current = data.iloc[i]
        prev = data.iloc[i-1]
        
        # Bullish Engulfing
        if (current['Close'] > current['Open'] and 
            prev['Close'] < prev['Open'] and 
            current['Close'] > prev['Open'] and 
            current['Open'] < prev['Close']):
            data.iloc[i, data.columns.get_loc('Engulf')] = 'BULL_ENGULF'
        
        # Bearish Engulfing
        elif (current['Close'] < current['Open'] and 
              prev['Close'] > prev['Open'] and 
              current['Close'] < prev['Open'] and 
              current['Open'] > prev['Close']):
            data.iloc[i, data.columns.get_loc('Engulf')] = 'BEAR_ENGULF'
    
    # Pin Bars
    def pinbar(row):
        body = abs(row['Close'] - row['Open'])
        upper_wick = row['High'] - max(row['Close'], row['Open'])
        lower_wick = min(row['Close'], row['Open']) - row['Low']
        
        if lower_wick > body * 2:
            return 'BULL_PIN'
        if upper_wick > body * 2:
            return 'BEAR_PIN'
        return None
    
    data['PinBar'] = data.apply(pinbar, axis=1)
    
    # Break of Structure
    data['Higher_High'] = data['High'] > data['High'].shift(1)
    data['Lower_Low'] = data['Low'] < data['Low'].shift(1)
    
    return data


def generate_signal(data):
    latest = data.iloc[-1]
    
    # תנאי קנייה - כל התנאים חייבים להתקיים
    buy_conditions = [
        latest['Close'] > latest['VWAP'],
        latest['SMA50'] > latest['SMA200'],
        latest['MACD'] > 0,
        latest['Engulf'] == 'BULL_ENGULF' or latest['PinBar'] == 'BULL_PIN'
    ]
    
    # תנאי מכירה - כל התנאים חייבים להתקיים
    sell_conditions = [
        latest['Close'] < latest['VWAP'],
        latest['SMA50'] < latest['SMA200'],
        latest['MACD'] < 0,
        latest['Engulf'] == 'BEAR_ENGULF' or latest['PinBar'] == 'BEAR_PIN'
    ]
    
    if all(buy_conditions):
        return 'BUY'
    elif all(sell_conditions):
        return 'SELL'
    else:
        return 'HOLD'


def calculate_sl_tp(data, signal):
    latest = data.iloc[-1]
    atr = latest['ATR']
    price = latest['Close']
    
    SL_MULT = 1.0
    TP_MULT = 2.0
    
    if signal == 'BUY':
        return price - (atr * SL_MULT), price + (atr * TP_MULT)
    elif signal == 'SELL':
        return price + (atr * SL_MULT), price - (atr * TP_MULT)
    else:
        return None, None


def run_bot():
    print("\n" + "="*50)
    print(f"🤖 Gold Bot Running at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*50)

    data = None
    used_symbol = None

    for symbol in DEFAULT_SYMBOLS:
        data = fetch_yahoo_fast(symbol, interval="1h", period_days=90)
        if not data.empty and len(data) > 200:
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

    signal = generate_signal(data)
    latest = data.iloc[-1]
    price = float(latest['Close'])
    rsi = float(latest['RSI'])

    print(f"\n📊 Analysis Results:")
    print(f"   Symbol: {used_symbol}")
    print(f"   Price: ${price:.2f}")
    print(f"   RSI: {rsi:.1f}")
    print(f"   VWAP: ${latest['VWAP']:.2f}")
    print(f"   SMA50: ${latest['SMA50']:.2f}")
    print(f"   SMA200: ${latest['SMA200']:.2f}")
    print(f"   MACD: {latest['MACD']:.2f}")
    print(f"   Engulf: {latest['Engulf']}")
    print(f"   Pin Bar: {latest['PinBar']}")
    print(f"   Signal: {signal}")

    if signal != 'HOLD':
        stop_loss, take_profit = calculate_sl_tp(data, signal)
        risk = abs(price - stop_loss)
        reward = abs(take_profit - price)
        risk_reward_ratio = reward / risk if risk > 0 else 0
        
        message = f"""
🏆 **XAU/USD SIGNAL ALERT** 🏆

📍 Signal: **{signal}**
💰 Price: ${price:.2f}
📊 Symbol: {used_symbol}

🎯 Take Profit: ${take_profit:.2f} (+${reward:.2f})
🛑 Stop Loss: ${stop_loss:.2f} (-${risk:.2f})
📈 Risk/Reward: 1:{risk_reward_ratio:.1f}

📊 **Indicators:**
- VWAP: ${latest['VWAP']:.2f}
- SMA50: ${latest['SMA50']:.2f}
- SMA200: ${latest['SMA200']:.2f}
- EMA20: ${latest['EMA20']:.2f}
- RSI: {rsi:.1f}
- MACD: {latest['MACD']:.2f}

🎯 **Price Action:**
- Engulfing: {latest['Engulf'] if latest['Engulf'] else 'None'}
- Pin Bar: {latest['PinBar'] if latest['PinBar'] else 'None'}
- Structure: {'🟢 Higher High' if latest['Higher_High'] else '🔴 Lower Low' if latest['Lower_Low'] else 'Neutral'}

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
VWAP: ${latest['VWAP']:.2f}
RSI: {rsi:.1f}
Golden Cross: {'✅ Yes' if latest['SMA50'] > latest['SMA200'] else '❌ No'}
Price Action: {latest['Engulf'] if latest['Engulf'] else latest['PinBar'] if latest['PinBar'] else 'No Pattern'}
Signal: No action needed

Next check in 30 minutes...
"""
            send_telegram_message(status_msg)
            print("📨 Status update sent")

    print("\n✅ Bot run completed successfully!")


if __name__ == "__main__":
    run_bot()
