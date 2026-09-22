import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Ayarları
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Eksik Değişkenler
EXCHANGE_OWNER_TYPE = "exchange"
