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
# COIN EVRENİ (Bybit'teki TÜM USDT çiftleri taranır, statik liste yok)
# ---------------------------------------------------------------------------
# Yüksek hacimli: 24 saatlik hacmi bu tutarın üzerindeki coinler WebSocket ile
# canlı izlenir (hacim patlaması, alış/satış dengesizliği, balina tespiti, RSI/MACD sinyali)
HIGH_VOLUME_USD_THRESHOLD = 5_000_000

# Düşük hacimli ama izlenmeye değer: tahmini haftalık hacmi bu tutarın üzerindeki
# coinler periyodik (15 dk'da bir) REST kontrolü ile izlenir, sadece hacim artışı bakılır
LOW_VOLUME_WEEKLY_USD_THRESHOLD = 2_000_000

# Kaynak kullanımını sınırlamak için WebSocket'e abone olunacak maksimum coin sayısı
# (en yüksek hacimliden başlayarak seçilir)
MAX_HIGH_VOLUME_SYMBOLS = 40

# Coin evreninin ne sıklıkla yeniden taranacağı (yeni coinler / hacim değişimi için)
SYMBOL_REFRESH_SECONDS = 3600  # 1 saat

# Düşük hacimli coinlerin ne sıklıkla REST ile kontrol edileceği
LOW_VOLUME_POLL_SECONDS = 900  # 15 dakika

# ---------------------------------------------------------------------------
# WHALE ALERT (on-chain büyük transfer) AYARLARI - opsiyonel, API key gerekir
# ---------------------------------------------------------------------------
WHALE_MIN_USD_VALUE = 1_000_000
WHALE_POLL_INTERVAL_SECONDS = 30

# ---------------------------------------------------------------------------
# HACİM / ALIŞ-SATIŞ AKIŞI AYARLARI (yüksek hacimli coinler için)
# ---------------------------------------------------------------------------
VOLUME_WINDOW_SECONDS = 300           # 5 dakikalık pencere
VOLUME_SPIKE_MULTIPLIER = 3.0         # Ortalamanın 3 katı hacim -> uyarı
TRADE_IMBALANCE_THRESHOLD = 0.70      # Alım/satım oranı %70'i geçerse uyarı
MIN_NOTIONAL_FOR_IMBALANCE_USD = 500_000

# ---------------------------------------------------------------------------
# BALİNA TESPİTİ (borsa verisinden, API key gerekmez)
# ---------------------------------------------------------------------------
# Tek bir işlemin bu tutarı aşması durumunda "büyük tekil işlem" olarak bildirilir
WHALE_SINGLE_TRADE_USD = 50_000

# "Birikim" (accumulation) tespiti: uzun bir pencerede sürekli alım baskısı
ACCUMULATION_WINDOW_SECONDS = 3600     # 1 saatlik pencere
ACCUMULATION_BUY_RATIO_THRESHOLD = 0.65
ACCUMULATION_MIN_NOTIONAL_USD = 1_000_000
ACCUMULATION_ALERT_COOLDOWN_SECONDS = 3600  # aynı coin için en fazla saatte bir uyarı

# ---------------------------------------------------------------------------
# RSI + MACD SİNYAL AYARLARI (yüksek hacimli coinler, saatlik mumlar)
# ---------------------------------------------------------------------------
SIGNAL_CHECK_INTERVAL_SECONDS = 3600  # saatlik kontrol
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
SIGNAL_ALERT_COOLDOWN_SECONDS = 3600  # aynı coin için en fazla saatte bir sinyal

# ---------------------------------------------------------------------------
# VERİTABANI
# ---------------------------------------------------------------------------
DB_PATH = "whale_bot.db"
