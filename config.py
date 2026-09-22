"""
Whale Tracking Bot - Ayarlar
Tüm eşik değerlerini ve API anahtarlarını burada yönetiyoruz.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# VERİTABANI
# ---------------------------------------------------------------------------
DB_PATH = os.getenv("DB_PATH", "whale_bot.db")

# ---------------------------------------------------------------------------
# API ANAHTARLARI (.env dosyasından okunur, koda asla direkt yazma!)
# ---------------------------------------------------------------------------
WHALE_ALERT_API_KEY = os.getenv("WHALE_ALERT_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
BYBIT_TESTNET_API_KEY = os.getenv("BYBIT_TESTNET_API_KEY", "")
BYBIT_TESTNET_API_SECRET = os.getenv("BYBIT_TESTNET_API_SECRET", "")

# ---------------------------------------------------------------------------
# OTOMATİK ALIM/SATIM (Bybit TESTNET - sahte para, gerçek risk yok)
# ---------------------------------------------------------------------------
TRADING_ENABLED = os.getenv("TRADING_ENABLED", "false").lower() == "true"
BYBIT_TESTNET_REST_BASE = "https://api-testnet.bybit.com"

POSITION_SIZE_USD = 100          # Her işlemde kullanılacak sabit tutar (testnet parası)
STOP_LOSS_PERCENT = 2.0          # Girişten %2 aşağıda zarar durdur
TAKE_PROFIT_PERCENT = 4.0        # Girişten %4 yukarıda kâr al
MAX_OPEN_POSITIONS = 5           # Aynı anda en fazla kaç pozisyon açık olabilir
POSITION_MONITOR_INTERVAL_SECONDS = 30  # Açık pozisyonlar ne sıklıkla kontrol edilir

# ---------------------------------------------------------------------------
# COIN EVRENİ (Bybit'teki TÜM USDT çiftleri taranır, statik liste yok)
# ---------------------------------------------------------------------------
HIGH_VOLUME_USD_THRESHOLD = 5_000_000
LOW_VOLUME_WEEKLY_USD_THRESHOLD = 2_000_000
MAX_HIGH_VOLUME_SYMBOLS = 40
SYMBOL_REFRESH_SECONDS = 3600  # 1 saat
LOW_VOLUME_POLL_SECONDS = 900  # 15 dakika

# ---------------------------------------------------------------------------
# EN ÇOK YÜKSELEN COİNLER
# ---------------------------------------------------------------------------
GAINERS_MIN_PCT = 10.0          
GAINERS_LIMIT = 10              
GAINERS_REFRESH_SECONDS = 900   

# ---------------------------------------------------------------------------
# WHALE ALERT
# ---------------------------------------------------------------------------
WHALE_MIN_USD_VALUE = 1_000_000
WHALE_POLL_INTERVAL_SECONDS = 30
EXCHANGE_OWNER_TYPE = "exchange"

# ---------------------------------------------------------------------------
# HACİM / ALIŞ-SATIŞ AKIŞI AYARLARI
# ---------------------------------------------------------------------------
VOLUME_WINDOW_SECONDS = 300           
VOLUME_SPIKE_MULTIPLIER = 3.0         
TRADE_IMBALANCE_THRESHOLD = 0.70      
MIN_NOTIONAL_FOR_IMBALANCE_USD = 500_000

# ---------------------------------------------------------------------------
# BALİNA TESPİTİ
# ---------------------------------------------------------------------------
WHALE_SINGLE_TRADE_USD = 50_000
ACCUMULATION_WINDOW_SECONDS = 3600     
ACCUMULATION_BUY_RATIO_THRESHOLD = 0.65
ACCUMULATION_MIN_NOTIONAL_USD = 1_000_000
ACCUMULATION_ALERT_COOLDOWN_SECONDS = 3600  

# ---------------------------------------------------------------------------
# RSI + MACD SİNYAL AYARLARI
# ---------------------------------------------------------------------------
SIGNAL_CHECK_INTERVAL_SECONDS = 3600  
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
SIGNAL_ALERT_COOLDOWN_SECONDS = 3600  
