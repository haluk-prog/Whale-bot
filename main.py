"""
Whale Tracking Bot - Ana giriş noktası
Çalıştırmak için: python main.py
"""

import asyncio

from database import init_db
from exchange_monitor import run_exchange_monitor
from whale_alert_monitor import poll_whale_alert
from notifier import send_telegram_message


async def main():
    init_db()
    send_telegram_message("🤖 Whale Tracking Bot başlatıldı.")
    await asyncio.gather(
        run_exchange_monitor(),
        poll_whale_alert(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INFO] Bot durduruldu.")
