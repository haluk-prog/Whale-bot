"""
Whale Tracking Bot - On-chain balina transferi izleyici
Whale Alert API (https://docs.whale-alert.io) kullanır.
Ücretsiz katmanda gecikmeli veri ve düşük istek limiti olabilir;
ihtiyaç halinde Etherscan/BscScan gibi zincire özel API'lerle genişletilebilir.
"""

import asyncio
import time

import requests

import config

# Config değişkenlerini çökme riskine karşı güvenli yükleme
WHALE_ALERT_API_KEY = getattr(config, 'WHALE_ALERT_API_KEY', '')
WHALE_MIN_USD_VALUE = getattr(config, 'WHALE_MIN_USD_VALUE', 1000000)
WHALE_POLL_INTERVAL_SECONDS = getattr(config, 'WHALE_POLL_INTERVAL_SECONDS', 30)
EXCHANGE_OWNER_TYPE = getattr(config, 'EXCHANGE_OWNER_TYPE', 'exchange')

from database import insert_whale_transfer, log_alert
from notifier import send_telegram_message

WHALE_ALERT_URL = "https://api.whale-alert.io/v1/transactions"


def classify_direction(from_type: str, to_type: str) -> str:
    if to_type == EXCHANGE_OWNER_TYPE and from_type != EXCHANGE_OWNER_TYPE:
        return "to_exchange"      # Borsaya giriş -> olası satış sinyali
    if from_type == EXCHANGE_OWNER_TYPE and to_type != EXCHANGE_OWNER_TYPE:
        return "from_exchange"    # Borsadan çıkış -> olası biriktirme sinyali
    return "wallet_to_wallet"


def format_alert(tx: dict) -> str:
    direction_labels = {
        "to_exchange": "🔴 Borsaya Giriş (olası satış baskısı)",
        "from_exchange": "🟢 Borsadan Çıkış (olası biriktirme)",
        "wallet_to_wallet": "⚪ Cüzdandan Cüzdana",
    }
    label = direction_labels.get(tx["direction"], tx["direction"])
    return (
        f"🐋 *Balina Hareketi* — {tx['symbol'].upper()}\n"
        f"{label}\n"
        f"Miktar: {tx['amount']:,.2f} {tx['symbol'].upper()} (${tx['amount_usd']:,.0f})\n"
        f"Kaynak: {tx['from_type']} → Hedef: {tx['to_type']}"
    )


async def poll_whale_alert():
    if not WHALE_ALERT_API_KEY:
        print("[UYARI] WHALE_ALERT_API_KEY tanımlı değil. Bu modül pasif kalacak.")
        return

    last_timestamp = int(time.time()) - 60  # başlangıçta son 1 dakikayı tara

    while True:
        try:
            params = {
                "api_key": WHALE_ALERT_API_KEY,
                "min_value": WHALE_MIN_USD_VALUE,
                "start": last_timestamp,
                "limit": 100,
            }
            resp = requests.get(WHALE_ALERT_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            for t in data.get("transactions", []):
                from_type = t.get("from", {}).get("owner_type", "unknown")
                to_type = t.get("to", {}).get("owner_type", "unknown")
                direction = classify_direction(from_type, to_type)

                tx = {
                    "tx_hash": t.get("hash", ""),
                    "symbol": t.get("symbol", ""),
                    "amount": t.get("amount", 0),
                    "amount_usd": t.get("amount_usd", 0),
                    "from_type": from_type,
                    "to_type": to_type,
                    "direction": direction,
                    "timestamp": t.get("timestamp", int(time.time())),
                }
                insert_whale_transfer(tx)

                msg = format_alert(tx)
                send_telegram_message(msg)
                log_alert("whale_transfer", tx["symbol"], msg)

            last_timestamp = int(time.time())

        except requests.RequestException as e:
            print(f"[HATA] Whale Alert isteği başarısız: {e}")

        await asyncio.sleep(WHALE_POLL_INTERVAL_SECONDS)
