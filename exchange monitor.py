"""
Whale Tracking Bot - Borsa hacim / alış-satış akışı izleyici
Binance'in genel (API key gerektirmeyen) WebSocket akışını kullanır: @aggTrade

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

BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream"


def build_stream_url(symbols):
    streams = "/".join(f"{s}@aggTrade" for s in symbols)
    return f"{BINANCE_WS_BASE}?streams={streams}"


async def listen_trades():
    """Binance aggTrade akışına bağlanır ve her trade'i veritabanına yazar."""
    url = build_stream_url(SYMBOLS)
    backoff = 1
    while True:
        try:
            async with websockets.connect(url, ping_interval=20) as ws:
                print(f"[OK] Binance WebSocket bağlantısı kuruldu ({len(SYMBOLS)} sembol)")
                backoff = 1
                async for raw_msg in ws:
                    msg = json.loads(raw_msg)
                    data = msg.get("data", {})
                    if not data:
                        continue
                    symbol = data["s"].upper()
                    price = float(data["p"])
                    qty = float(data["q"])
                    quote_qty = price * qty
                    is_buyer_maker = data["m"]  # True -> satıcı taker (satış baskısı)
                    ts = int(data["T"] / 1000)
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
