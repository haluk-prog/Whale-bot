"""
Whale Tracking Bot - Ayarlar
Tüm eşik değerlerini ve API anahtarlarını burada yönetiyoruz.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# API ANAHTARLARI (.env dosyasından okunur, koda asla direkt yazma!)
# ---------------------------------------------------------------------------
WHALE_ALERT_API_KEY = os.getenv("WHALE_ALERT_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ---------------------------------------------------------------------------
# TAKİP EDİLECEK BORSA SEMBOLLERİ (Binance formatında)
# ---------------------------------------------------------------------------
SYMBOLS = ["btcusdt", "ethusdt", "solusdt", "bnbusdt", "xrpusdt"]

# ---------------------------------------------------------------------------
# WHALE ALERT (on-chain büyük transfer) AYARLARI
# ---------------------------------------------------------------------------
WHALE_MIN_USD_VALUE = 1_000_000       # Bu tutarın üzerindeki transferler izlenir
WHALE_POLL_INTERVAL_SECONDS = 30      # Kaç saniyede bir kontrol edilecek

# ---------------------------------------------------------------------------
# HACİM / ALIŞ-SATIŞ AKIŞI AYARLARI
# ---------------------------------------------------------------------------
VOLUME_WINDOW_SECONDS = 300           # 5 dakikalık pencere
VOLUME_SPIKE_MULTIPLIER = 3.0         # Ortalamanın 3 katı hacim -> uyarı
TRADE_IMBALANCE_THRESHOLD = 0.70      # Alım/satım oranı %70'i geçerse uyarı
MIN_NOTIONAL_FOR_IMBALANCE_USD = 500_000  # Pencere içindeki minimum toplam hacim

# ---------------------------------------------------------------------------
# BORSAYA GİRİŞ/ÇIKIŞ SINIFLANDIRMASI İÇİN BİLİNEN BORSA CÜZDAN ETİKETLERİ
# (Whale Alert zaten "from"/"to" alanlarında owner_type=exchange bilgisini verir)
# ---------------------------------------------------------------------------
EXCHANGE_OWNER_TYPE = "exchange"

# ---------------------------------------------------------------------------
# VERİTABANI
# ---------------------------------------------------------------------------
DB_PATH = "whale_bot.db"
