import os
import requests

def send_telegram_message(message: str):
    """
    Telegram Bot API kullanarak belirtilen mesaja bildirim atar.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("Uyarı: TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID ortam değişkenleri tanımlı değil.")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Telegram mesajı gönderilirken hata oluştu: {e}")
