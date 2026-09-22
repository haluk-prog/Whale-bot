import os
import time
import requests
import pandas as pd
import pandas_ta as ta

# Railway / Çevre Değişkenleri
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BYBIT_BASE_URL = "https://api.bybit.com"

def send_telegram_message(message):
    """Telegram botu üzerinden mesaj gönderir."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram Token veya Chat ID bulunamadı! Variables kısmını kontrol edin.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"❌ Telegram mesajı gönderilirken hata oluştu: {e}")

def get_top_volume_usdt_pairs(limit=20):
    """Bybit Spot piyasasından en yüksek 24s hacimli USDT çiftlerini getirir."""
    endpoint = f"{BYBIT_BASE_URL}/v5/market/tickers"
    params = {"category": "spot"}
    
    try:
        response = requests.get(endpoint, params=params).json()
        tickers = response.get("result", {}).get("list", [])
        
        # Sadece USDT ile biten çiftleri filtrele
        usdt_pairs = [item for item in tickers if item['symbol'].endswith('USDT')]
        
        # 24s İşlem Hacmine (turnover / quoteVolume) göre sırala
        sorted_pairs = sorted(usdt_pairs, key=lambda x: float(x.get('turnover', 0)), reverse=True)
        return [p['symbol'] for p in sorted_pairs[:limit]]
    except Exception as e:
        print(f"❌ Bybit sembol listesi çekilirken hata: {e}")
        return []

def get_klines(symbol, interval, limit=100):
    """Bybit V5 API üzerinden kline/mum verilerini çeker."""
    endpoint = f"{BYBIT_BASE_URL}/v5/market/kline"
    params = {
        "category": "spot",
        "symbol": symbol,
        "interval": interval,  # "5" (5dk) veya "D" (Günlük)
        "limit": limit
    }
    
    response = requests.get(endpoint, params=params).json()
    kline_list = response.get("result", {}).get("list", [])
    
    # Bybit verileri yeniden eskiye sıralı döndürür, kronolojik olarak ters çeviriyoruz
    kline_list.reverse()
    
    df = pd.DataFrame(kline_list, columns=[
        'startTime', 'openPrice', 'highPrice', 'lowPrice', 'closePrice', 'volume', 'turnover'
    ])
    df['close'] = df['closePrice'].astype(float)
    df['volume'] = df['volume'].astype(float)
    return df

def analyze_symbol(symbol):
    """Bybit verileriyle MA hesaplamalarını ve sinyal kontrollerini yapar."""
    try:
        # 5 Dakikalık Veri ("5")
        df_5m = get_klines(symbol, "5", limit=50)
        df_5m['MA7'] = ta.sma(df_5m['close'], length=7)
        df_5m['MA14'] = ta.sma(df_5m['close'], length=14)
        
        # Günlük Veri ("D")
        df_1d = get_klines(symbol, "D", limit=100)
        df_1d['MA50'] = ta.sma(df_1d['close'], length=50)
        
        close_5m = df_5m['close'].iloc[-1]
        volume_5m = df_5m['volume'].iloc[-1]
        ma7_5m = df_5m['MA7'].iloc[-1]
        ma14_5m = df_5m['MA14'].iloc[-1]
        
        close_1d = df_1d['close'].iloc[-1]
        ma50_1d = df_1d['MA50'].iloc[-1]

        signals = []

        # 5 Dakikalık Sinyaller
        if close_5m > ma7_5m and close_5m > ma14_5m:
            signals.append("🟢 *GÜÇLÜ AL* (5d: Fiyat MA7 ve MA14 Üstünde)")
        elif close_5m > ma7_5m:
            signals.append("🟢 *AL* (5d: Fiyat MA7 Üstünde)")

        if close_5m < ma7_5m and close_5m < ma14_5m:
            signals.append("🔴 *GÜÇLÜ SAT* (5d: Kapanış MA7 ve MA14 Altında)")
        elif close_5m < ma7_5m:
            signals.append("🔴 *SAT* (5d: Kapanış MA7 Altında)")

        # Günlük Sinyaller
        if close_1d > ma50_1d:
            signals.append("ℹ️ *BİLGİ:* Günlükte MA50 Üstünde (Trend Pozitif)")
        else:
            signals.append("ℹ️ *BİLGİ:* Günlükte MA50 Altında (Trend Negatif)")

        tg_message = f"🟡 *Bybit:* `{symbol}`\n"
        tg_message += f"💰 *Fiyat:* `{close_5m:.4f}` USDT\n"
        tg_message += f"📈 *Hacim (5d):* `{volume_5m:.2f}`\n"
        tg_message += f"🔹 *MA7:* `{ma7_5m:.4f}` | *MA14:* `{ma14_5m:.4f}` | *1d MA50:* `{ma50_1d:.4f}`\n\n"
        tg_message += "*Sinyaller:*\n"
        
        for sig in signals:
            tg_message += f"{sig}\n"

        send_telegram_message(tg_message)

    except Exception as e:
        print(f"❌ {symbol} analiz hatası: {e}")

def run_bot():
    print("🚀 Bybit Kripto Sinyal Botu Taraması Başladı...\n")
    top_20 = get_top_volume_usdt_pairs(limit=20)

    for symbol in top_20:
        analyze_symbol(symbol)
        time.sleep(0.3)

if __name__ == "__main__":
    while True:
        run_bot()
        print("\n⏳ 5 dakika bekleniyor...\n")
        time.sleep(300)
