"""
Whale Tracking Bot - Borsa izleme motoru

Bybit'in genel (API key gerektirmeyen) WebSocket ve REST API'lerini kullanır.
Coin evreni dinamik olarak taranır (statik liste yok):

  - YÜKSEK HACİMLİ coinler (24s hacim >= eşik): WebSocket ile canlı izlenir
      -> hacim patlaması, alış/satış dengesizliği, büyük tekil işlem (balina),
         sürekli alım birikimi, saatlik RSI+MACD yükseliş kesişimi
  - DÜŞÜK HACİMLİ coinler (haftalık tahmini hacim eşik üzerinde): periyodik
    REST kontrolü ile hacim artışı izlenir (daha az sıklıkta, daha az spam)

Not: Binance.com ABD sunucularından (Railway dahil) gelen bağlantıları
bölgesel kısıtlama nedeniyle reddettiği için Bybit kullanıyoruz.
"""

import asyncio
import json
import time

import requests
import websockets

from config import (
    VOLUME_WINDOW_SECONDS,
    VOLUME_SPIKE_MULTIPLIER,
    TRADE_IMBALANCE_THRESHOLD,
    MIN_NOTIONAL_FOR_IMBALANCE_USD,
    WHALE_SINGLE_TRADE_USD,
    ACCUMULATION_WINDOW_SECONDS,
    ACCUMULATION_BUY_RATIO_THRESHOLD,
    ACCUMULATION_MIN_NOTIONAL_USD,
    ACCUMULATION_ALERT_COOLDOWN_SECONDS,
    SYMBOL_REFRESH_SECONDS,
    LOW_VOLUME_POLL_SECONDS,
    SIGNAL_CHECK_INTERVAL_SECONDS,
    SIGNAL_ALERT_COOLDOWN_SECONDS,
)
from database import (
    insert_trade,
    get_recent_trade_stats,
    get_average_volume,
    prune_old_trades,
    log_alert,
    has_recent_alert,
)
from notifier import send_telegram_message
from signals import (
    fetch_all_usdt_symbols_with_volume,
    classify_symbols,
    check_bullish_crossover,
)
from ma_signals import check_5m_signal, check_15m_signal

BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/spot"
BYBIT_REST_BASE = "https://api.bybit.com"

# ---------------------------------------------------------------------------
# PAYLAŞILAN DURUM (farklı görevler arasında coin listelerini paylaşmak için)
# ---------------------------------------------------------------------------
_state = {
    "high_volume_symbols": [],
    "low_volume_symbols": [],
    "low_volume_baseline": {},  # {symbol: son_bilinen_24s_hacim}
}


def _chunk(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


async def refresh_universe_loop():
    """Coin evrenini periyodik olarak yeniden tarar ve sınıflandırır."""
    while True:
        try:
            all_symbols = fetch_all_usdt_symbols_with_volume()
            high_vol, low_vol = classify_symbols(all_symbols)
            _state["high_volume_symbols"] = high_vol
            _state["low_volume_symbols"] = low_vol
            print(f"[TARAMA] {len(high_vol)} yüksek hacimli, {len(low_vol)} düşük hacimli coin bulundu.")
        except requests.RequestException as e:
            print(f"[HATA] Coin evreni taranamadı: {e}")

        await asyncio.sleep(SYMBOL_REFRESH_SECONDS)


async def listen_trades():
    """
    Yüksek hacimli coinlerin Bybit publicTrade akışını dinler.
    Coin listesi periyodik olarak yenilendiği için bağlantı da düzenli
    aralıklarla yeniden kurulur (yeni coinleri kapsamak için).
    """
    backoff = 1
    while True:
        symbols = _state["high_volume_symbols"]
        if not symbols:
            await asyncio.sleep(5)
            continue

        try:
            async with websockets.connect(BYBIT_WS_URL, ping_interval=None) as ws:
                topics = [f"publicTrade.{s}" for s in symbols]
                for chunk in _chunk(topics, 10):
                    await ws.send(json.dumps({"op": "subscribe", "args": chunk}))
                    await asyncio.sleep(0.2)

                print(f"[OK] Bybit WebSocket bağlantısı kuruldu ({len(symbols)} sembol)")
                backoff = 1
                last_ping = time.time()
                connection_start = time.time()

                async for raw_msg in ws:
                    if time.time() - last_ping > 18:
                        await ws.send(json.dumps({"op": "ping"}))
                        last_ping = time.time()

                    # Coin listesi değiştiyse bağlantıyı yenilemek için kopar
                    if time.time() - connection_start > SYMBOL_REFRESH_SECONDS:
                        break

                    msg = json.loads(raw_msg)
                    if msg.get("op") in ("subscribe", "ping", "pong"):
                        continue

                    topic = msg.get("topic", "")
                    if not topic.startswith("publicTrade."):
                        continue

                    for trade in msg.get("data", []):
                        await _handle_trade(trade)

        except (websockets.ConnectionClosed, OSError) as e:
            print(f"[HATA] WebSocket koptu ({e}), {backoff}s sonra yeniden bağlanılıyor...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


async def _handle_trade(trade):
    """Tek bir işlemi işler: veritabanına yazar + büyük tekil işlem kontrolü yapar."""
    symbol = trade["s"].upper()
    price = float(trade["p"])
    qty = float(trade["v"])
    quote_qty = price * qty
    is_sell_side = trade["S"] == "Sell"  # taker satıcıysa satış baskısı
    ts = int(int(trade["T"]) / 1000)

    insert_trade(symbol, price, qty, quote_qty, is_sell_side, ts)

    # --- Büyük tekil işlem (balina) tespiti ---
    if quote_qty >= WHALE_SINGLE_TRADE_USD:
        direction = "🔴 Satış" if is_sell_side else "🟢 Alış"
        msg = (
            f"🐳 *Büyük Tekil İşlem* — {symbol}\n"
            f"{direction} — ${quote_qty:,.0f} (fiyat: {price:,.4f})"
        )
        send_telegram_message(msg)
        log_alert("whale_single_trade", symbol, msg)


async def analyze_flow_loop():
    """Periyodik olarak hacim, alış/satış dengesi ve birikim durumunu kontrol eder."""
    while True:
        await asyncio.sleep(VOLUME_WINDOW_SECONDS)
        symbols = list(_state["high_volume_symbols"])

        for symbol in symbols:
            buy_vol, sell_vol = get_recent_trade_stats(symbol, VOLUME_WINDOW_SECONDS)
            total_vol = buy_vol + sell_vol
            if total_vol >= MIN_NOTIONAL_FOR_IMBALANCE_USD:
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

            # --- Balina birikimi (accumulation) kontrolü, daha uzun pencere ---
            acc_buy, acc_sell = get_recent_trade_stats(symbol, ACCUMULATION_WINDOW_SECONDS)
            acc_total = acc_buy + acc_sell
            if acc_total >= ACCUMULATION_MIN_NOTIONAL_USD:
                acc_buy_ratio = acc_buy / acc_total
                if acc_buy_ratio >= ACCUMULATION_BUY_RATIO_THRESHOLD:
                    if not has_recent_alert("accumulation", symbol, ACCUMULATION_ALERT_COOLDOWN_SECONDS):
                        msg = (
                            f"📈 *Olası Balina Birikimi* — {symbol}\n"
                            f"Son {ACCUMULATION_WINDOW_SECONDS // 60} dk: alım ${acc_buy:,.0f} "
                            f"({acc_buy_ratio:.0%})  |  satım ${acc_sell:,.0f}\n"
                            f"Sürekli ve baskın alım tespit edildi."
                        )
                        send_telegram_message(msg)
                        log_alert("accumulation", symbol, msg)

        prune_old_trades()


async def low_volume_poll_loop():
    """Düşük hacimli coinleri periyodik olarak REST ile kontrol eder (hafif yük)."""
    while True:
        await asyncio.sleep(LOW_VOLUME_POLL_SECONDS)
        symbols = list(_state["low_volume_symbols"])
        if not symbols:
            continue

        try:
            url = f"{BYBIT_REST_BASE}/v5/market/tickers"
            resp = requests.get(url, params={"category": "spot"}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            print(f"[HATA] Düşük hacimli coin taraması başarısız: {e}")
            continue

        current_volumes = {}
        for item in data.get("result", {}).get("list", []):
            sym = item.get("symbol", "")
            if sym in symbols:
                try:
                    current_volumes[sym] = float(item.get("turnover24h", 0))
                except (TypeError, ValueError):
                    continue

        for symbol, current_vol in current_volumes.items():
            baseline = _state["low_volume_baseline"].get(symbol)
            if baseline and baseline > 0 and current_vol > baseline * VOLUME_SPIKE_MULTIPLIER:
                if not has_recent_alert("low_volume_spike", symbol, LOW_VOLUME_POLL_SECONDS):
                    msg = (
                        f"📊 *Hacim Artışı (düşük hacimli coin)* — {symbol}\n"
                        f"24s hacim: ${current_vol:,.0f} (öncekinin {current_vol / baseline:.1f} katı)"
                    )
                    send_telegram_message(msg)
                    log_alert("low_volume_spike", symbol, msg)
            _state["low_volume_baseline"][symbol] = current_vol


async def signal_check_loop():
    """Yüksek hacimli coinler için saatlik RSI+MACD yükseliş sinyali kontrolü."""
    while True:
        await asyncio.sleep(SIGNAL_CHECK_INTERVAL_SECONDS)
        symbols = list(_state["high_volume_symbols"])

        for symbol in symbols:
            if has_recent_alert("rsi_macd_signal", symbol, SIGNAL_ALERT_COOLDOWN_SECONDS):
                continue

            is_bullish, details = check_bullish_crossover(symbol)
            if is_bullish and details:
                msg = (
                    f"📈 *RSI+MACD Yükseliş Sinyali* — {symbol}\n"
                    f"RSI: {details['rsi']:.1f}  |  MACD: {details['macd']:.4f} > "
                    f"Sinyal: {details['signal']:.4f}\n"
                    f"Saatlik grafikte momentum yukarı yönlü."
                )
                send_telegram_message(msg)
                log_alert("rsi_macd_signal", symbol, msg)

            # Bybit rate limit'e takılmamak için istekler arasında küçük bekleme
            await asyncio.sleep(0.5)


async def ma_5m_signal_loop():
    """Her 5 dakikada bir, yüksek hacimli coinler için MA7 kesişimini kontrol eder."""
    while True:
        await asyncio.sleep(300)
        symbols = list(_state["high_volume_symbols"])
        for symbol in symbols:
            await check_5m_signal(symbol)
            await asyncio.sleep(0.3)  # Bybit rate limit'e takılmamak için


async def ma_15m_signal_loop():
    """Her 15 dakikada bir, yüksek hacimli coinler için MA7/14/21 + MACD kademeli sinyalini kontrol eder."""
    while True:
        await asyncio.sleep(900)
        symbols = list(_state["high_volume_symbols"])
        for symbol in symbols:
            await check_15m_signal(symbol)
            await asyncio.sleep(0.3)


async def run_exchange_monitor():
    # İlk taramayı diğer görevler başlamadan önce senkron şekilde yap
    try:
        all_symbols = fetch_all_usdt_symbols_with_volume()
        high_vol, low_vol = classify_symbols(all_symbols)
        _state["high_volume_symbols"] = high_vol
        _state["low_volume_symbols"] = low_vol
        print(f"[BAŞLANGIÇ] {len(high_vol)} yüksek hacimli, {len(low_vol)} düşük hacimli coin bulundu.")
    except requests.RequestException as e:
        print(f"[HATA] Başlangıç taraması başarısız, boş listeyle başlanıyor: {e}")

    await asyncio.gather(
        refresh_universe_loop(),
        listen_trades(),
        analyze_flow_loop(),
        low_volume_poll_loop(),
        signal_check_loop(),
        ma_5m_signal_loop(),
        ma_15m_signal_loop(),
    )
