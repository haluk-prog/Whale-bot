"""
Whale Tracking Bot - Borsa hacim / alış-satış akışı izleyici
Bybit'in genel (API key gerektirmeyen) WebSocket akışını kullanır: publicTrade

Not: Binance.com, ABD sunucularından (Railway dahil) gelen bağlantıları
bölgesel kısıtlama nedeniyle reddediyor (HTTP 451). Bybit bu kısıtlamayı
uygulamadığı için buluta deploy edilen botlar için daha uygun.

Her işlem geldiğinde veritabanına yazar; periyodik olarak:
  1) Hacim ani artışlarını (volume spike)
  2) Alış/satış dengesizliğini (buy/sell imbalance)
kontrol edip eşik aşılırsa Telegram'a bildirim gönderir.
"""

import asyncio
import json
import time

import websockets

from config import (
    SYMBOLS,
    VOLUME_WINDOW_SECONDS,
    VOLUME_SPIKE_MULTIPLIER,
    TRADE_IMBALANCE_THRESHOLD,
    MIN_NOTIONAL_FOR_IMBALANCE_USD,
)
from database import (
    insert_trade,
    get_recent_trade_stats,
    get_average_volume,
    prune_old_trades,
    log_alert,
)
from notifier import send_telegram_message

BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/spot"


async def listen_trades():
    """Bybit publicTrade akışına bağlanır ve her trade'i veritabanına yazar."""
    backoff = 1
    while True:
        try:
            async with websockets.connect(BYBIT_WS_URL, ping_interval=None) as ws:
                # Bybit'e abone olma isteği gönder
                topics = [f"publicTrade.{s.upper()}" for s in SYMBOLS]
                await ws.send(json.dumps({"op": "subscribe", "args": topics}))
                print(f"[OK] Bybit WebSocket bağlantısı kuruldu ({len(SYMBOLS)} sembol)")
                backoff = 1

                last_ping = time.time()

                async for raw_msg in ws:
                    # Bybit her 20 saniyede bir ping ister, yoksa bağlantıyı kapatır
                    if time.time() - last_ping > 18:
                        await ws.send(json.dumps({"op": "ping"}))
                        last_ping = time.time()

                    msg = json.loads(raw_msg)

                    if msg.get("op") in ("subscribe", "ping", "pong"):
                        continue

                    topic = msg.get("topic", "")
                    if not topic.startswith("publicTrade."):
                        continue

                    for trade in msg.get("data", []):
                        symbol = trade["s"].upper()
                        price = float(trade["p"])
                        qty = float(trade["v"])
                        quote_qty = price * qty
                        # Bybit'te "S" alanı: "Buy" -> taker alıcı (alış baskısı)
                        #                     "Sell" -> taker satıcı (satış baskısı)
                        is_buyer_maker = trade["S"] == "Sell"
                        ts = int(int(trade["T"]) / 1000)
                        insert_trade(symbol, price, qty, quote_qty, is_buyer_maker, ts)

        except (websockets.ConnectionClosed, OSError) as e:
            print(f"[HATA] WebSocket koptu ({e}), {backoff}s sonra yeniden bağlanılıyor...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


async def analyze_flow_loop():
    """Periyodik olarak hacim ve alış/satış dengesini kontrol eder."""
    while True:
        await asyncio.sleep(VOLUME_WINDOW_SECONDS)
        for symbol in [s.upper() for s in SYMBOLS]:
            buy_vol, sell_vol = get_recent_trade_stats(symbol, VOLUME_WINDOW_SECONDS)
            total_vol = buy_vol + sell_vol
            if total_vol < MIN_NOTIONAL_FOR_IMBALANCE_USD:
                continue

            # --- Hacim ani artışı kontrolü ---
            avg_vol = get_average_volume(symbol, VOLUME_WINDOW_SECONDS)
            if avg_vol > 0 and total_vol > avg_vol * VOLUME_SPIKE_MULTIPLIER:
                msg = (
                    f"📊 *Hacim Patlaması* — {symbol}\n"
                    f"Son {VOLUME_WINDOW_SECONDS // 60} dk hacim: ${total_vol:,.0f}\n"
                    f"Ortalamanın {total_vol / avg_vol:.1f} katı"
                )
                send_telegram_message(msg)
                log_alert("volume_spike", symbol, msg)

            # --- Alış/satış dengesizliği kontrolü ---
            buy_ratio = buy_vol / total_vol
            sell_ratio = sell_vol / total_vol
            if buy_ratio >= TRADE_IMBALANCE_THRESHOLD:
                msg = (
                    f"🟢 *Güçlü Alım Baskısı* — {symbol}\n"
                    f"Alım: ${buy_vol:,.0f} ({buy_ratio:.0%})  |  Satım: ${sell_vol:,.0f}"
                )
                send_telegram_message(msg)
                log_alert("buy_imbalance", symbol, msg)
            elif sell_ratio >= TRADE_IMBALANCE_THRESHOLD:
                msg = (
                    f"🔴 *Güçlü Satış Baskısı* — {symbol}\n"
                    f"Satım: ${sell_vol:,.0f} ({sell_ratio:.0%})  |  Alım: ${buy_vol:,.0f}"
                )
                send_telegram_message(msg)
                log_alert("sell_imbalance", symbol, msg)

        prune_old_trades()


async def run_exchange_monitor():
    await asyncio.gather(listen_trades(), analyze_flow_loop())

