import pandas as pd
import yfinance as yf
import ta
import requests
import numpy as np
from datetime import datetime
import os
import warnings
warnings.filterwarnings('ignore')

# קבל את הנתונים מהסביבה (בטוח יותר)
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

def send_telegram_message(message):
    """שלח הודעה לטלגרם"""
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

def calculate_indicators(data):
    """חשב את כל האינדיקטורים"""
    # ממוצעים נעים
    data['SMA20'] = ta.trend.sma_indicator(data['Close'], window=20)
    data['SMA50'] = ta.trend.sma_indicator(data['Close'], window=50)
    data['EMA20'] = ta.trend.ema_indicator(data['Close'], window=20)
    
    # RSI
    data['RSI'] = ta.momentum.rsi(data['Close'], window=14)
    
    # MACD
    macd = ta.trend.MACD(data['Close'])
    data['MACD'] = macd.macd_diff()
    
    # Bollinger Bands
    bb = ta.volatility.BollingerBands(data['Close'])
    data['BB_Upper'] = bb.bollinger_hband()
    data['BB_Lower'] = bb.bollinger_lband()
    
    # ATR לחישוב Stop Loss
    data['ATR'] = ta.volatility.average_true_range(
        data['High'], data['Low'], data['Close'], window=14
    )
    
    return data

def generate_signal(data):
    """צור סיגנל קנייה/מכירה"""
    latest = data.iloc[-1]
    
    # חשב ניקוד לקנייה
    buy_score = 0
    if latest['SMA20'] > latest['SMA50']:  # טרנד עולה
        buy_score += 2
    if latest['RSI'] < 70 and latest['RSI'] > 30:  # RSI באיזור בריא
        buy_score += 1
    if latest['MACD'] > 0:  # מומנטום חיובי
        buy_score += 1
    if latest['Close'] > latest['EMA20']:  # מעל הממוצע
        buy_score += 1
    if latest['Close'] < latest['BB_Upper']:  # לא קנוי מדי
        buy_score += 1
    
    # חשב ניקוד למכירה
    sell_score = 0
    if latest['SMA20'] < latest['SMA50']:  # טרנד יורד
        sell_score += 2
    if latest['RSI'] > 70 or latest['RSI'] < 30:  # RSI קיצוני
        sell_score += 1
    if latest['MACD'] < 0:  # מומנטום שלילי
        sell_score += 1
    if latest['Close'] < latest['EMA20']:  # מתחת לממוצע
        sell_score += 1
    if latest['Close'] > latest['BB_Lower']:  # לא מכור מדי
        sell_score += 1
    
    # החלט על סיגנל
    if buy_score >= 4:
        return 'BUY', buy_score
    elif sell_score >= 4:
        return 'SELL', sell_score
    else:
        return 'HOLD', max(buy_score, sell_score)

def calculate_sl_tp(data, signal):
    """חשב Stop Loss ו-Take Profit"""
    latest = data.iloc[-1]
    atr = latest['ATR']
    price = latest['Close']
    
    if signal == 'BUY':
        stop_loss = price - (atr * 1.5)
        take_profit = price + (atr * 3)
    elif signal == 'SELL':
        stop_loss = price + (atr * 1.5)
        take_profit = price - (atr * 3)
    else:
        return None, None
    
    return stop_loss, take_profit

def run_bot():
    """הפונקציה הראשית"""
    print("\n" + "="*50)
    print(f"🤖 Gold Bot Running at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*50)
    
    # נסה כמה סימבולים של זהב
    symbols = ['GC=F', 'GLD', 'IAU', 'GOLD']
    data = None
    used_symbol = None
    
    for symbol in symbols:
        try:
            print(f"📊 Trying {symbol}...")
            data = yf.download(
                symbol, 
                period="2mo",  # חודשיים
                interval="1h",  # נרות של שעה
                progress=False
            )
            if not data.empty and len(data) > 50:
                used_symbol = symbol
                print(f"✅ Success with {symbol}")
                break
        except Exception as e:
            print(f"❌ Failed {symbol}: {e}")
            continue
    
    if data is None or data.empty:
        message = "⚠️ Unable to fetch gold data from any source"
        print(message)
        send_telegram_message(message)
        return
    
    print(f"📈 Data loaded: {len(data)} candles")
    
    # חשב אינדיקטורים
    try:
        data = calculate_indicators(data)
        data = data.dropna()
        print(f"📊 Indicators calculated successfully")
    except Exception as e:
        print(f"❌ Error calculating indicators: {e}")
        return
    
    # צור סיגנל
    signal, score = generate_signal(data)
    latest = data.iloc[-1]
    price = float(latest['Close'])
    rsi = float(latest['RSI'])
    
    print(f"\n📊 Analysis Results:")
    print(f"   Symbol: {used_symbol}")
    print(f"   Price: ${price:.2f}")
    print(f"   RSI: {rsi:.1f}")
    print(f"   Signal: {signal} (Score: {score}/6)")
    
    # שלח הודעה אם יש סיגנל
    if signal != 'HOLD':
        stop_loss, take_profit = calculate_sl_tp(data, signal)
        
        # חשב יחס סיכון/סיכוי
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
        
        # שלח סטטוס כל כמה שעות
        hour = datetime.now().hour
        if hour % 6 == 0:  # כל 6 שעות
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