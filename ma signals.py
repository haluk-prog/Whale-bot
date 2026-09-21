"""
Whale Tracking Bot - Hareketli Ortalama (MA) + MACD sinyal modülü

Kurallar:
  5 dk   : Fiyat MA7 üzerine çıkarsa                          -> AL
  15 dk  : Fiyat MA7 ve MA14 üzerindeyse                       -> GÜÇLÜ AL
  15 dk  : Fiyat MA7, MA14, MA21 üzerinde VE
           MACD yukarı kesişim yaptıysa                        -> SÜPER AL
  15 dk  : Fiyat MA7 altında kapanırsa                          -> SAT
  15 dk  : Fiyat MA7 ve MA14 altındaysa                         -> GÜÇLÜ SAT
  15 dk  : Fiyat MA7, MA14, MA21 altında VE
           MACD aşağı kesişim yaptıysa                          -> SÜPER SAT

Her sinyal mesajında ilgili mumun hacim bilgisi de paylaşılır.
Spam olmaması için: durum SÜRDÜĞÜ sürece tekrar mesaj gönderilmez,
sadece bir önceki kontrole göre durum DEĞİŞTİĞİNDE bildirim atılır
(örn. "SAT" durumundan "GÜÇLÜ AL" durumuna geçildiğinde).
"""

import requests

from config import MACD_FAST, MACD_SLOW, MACD_SIGNAL
from notifier import send_telegram_message

BYBIT_REST_BASE = "https://api.bybit.com"

MA_FAST = 7
MA_MID = 14
MA_SLOW = 21

# Sembol başına son bilinen durumu tutar (spam önleme için, bellek içinde)
_last_5m_state = {}
_last_15m_tier = {}


def fetch_closes_and_volumes(symbol, interval, limit=100):
    """Bybit'ten kapanış fiyatlarını ve mum hacimlerini (USDT) çeker, eskiden yeniye sıralı."""
    url = f"{BYBIT_REST_BASE}/v5/market/kline"
    params = {"category": "spot", "symbol": symbol, "interval": interval, "limit": limit}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    klines = data.get("result", {}).get("list", [])
    klines.reverse()  # Bybit en yeniyi en üstte döndürür, kronolojik sıraya çeviriyoruz
    closes = [float(k[4]) for k in klines]
    volumes = [float(k[6]) for k in klines]  # turnover (USDT cinsinden hacim)
    return closes, volumes


def calculate_sma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def calculate_ema_series(values, period):
    ema = [values[0]]
    multiplier = 2 / (period + 1)
    for price in values[1:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    return ema


def calculate_macd_series(closes, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL):
    if len(closes) < slow + signal + 1:
        return None, None
    ema_fast = calculate_ema_series(closes, fast)
    ema_slow = calculate_ema_series(closes, slow)
    min_len = min(len(ema_fast), len(ema_slow))
    macd_line = [ema_fast[-min_len:][i] - ema_slow[-min_len:][i] for i in range(min_len)]
    signal_line = calculate_ema_series(macd_line, signal)
    return macd_line, signal_line


def macd_crossover_direction(closes):
    """Son iki mumda MACD'nin sinyal çizgisini hangi yönde kestiğini döndürür."""
    macd_line, signal_line = calculate_macd_series(closes)
    if macd_line is None or len(macd_line) < 2 or len(signal_line) < 2:
        return None

    macd_now, macd_prev = macd_line[-1], macd_line[-2]
    signal_now, signal_prev = signal_line[-1], signal_line[-2]

    if macd_prev <= signal_prev and macd_now > signal_now:
        return "bullish"
    if macd_prev >= signal_prev and macd_now < signal_now:
        return "bearish"
    return None


def _format_volume_line(volumes, n_candles=1):
    total_vol = sum(volumes[-n_candles:])
    return f"Hacim: ${total_vol:,.0f}"


async def check_5m_signal(symbol):
    """5 dakikalık grafikte fiyat MA7 üzerine yeni çıktıysa AL sinyali üretir."""
    try:
        closes, volumes = fetch_closes_and_volumes(symbol, "5", limit=30)
    except requests.RequestException:
        return

    ma7 = calculate_sma(closes, MA_FAST)
    if ma7 is None or len(closes) < 2:
        return

    current_close = closes[-1]
    state = "above" if current_close > ma7 else "below"
    prev_state = _last_5m_state.get(symbol)
    _last_5m_state[symbol] = state

    if state == "above" and prev_state == "below":
        msg = (
            f"🟢 *AL* — {symbol} (5dk)\n"
            f"Fiyat MA7 üzerine çıktı: ${current_close:,.4f} > MA7: ${ma7:,.4f}\n"
            f"{_format_volume_line(volumes)}"
        )
        send_telegram_message(msg)


async def check_15m_signal(symbol):
    """15 dakikalık grafikte MA7/14/21 ve MACD'ye göre kademeli al/sat sinyali üretir."""
    try:
        closes, volumes = fetch_closes_and_volumes(symbol, "15", limit=60)
    except requests.RequestException:
        return

    ma7 = calculate_sma(closes, MA_FAST)
    ma14 = calculate_sma(closes, MA_MID)
    ma21 = calculate_sma(closes, MA_SLOW)
    if None in (ma7, ma14, ma21):
        return

    current_close = closes[-1]
    macd_direction = macd_crossover_direction(closes)

    above7 = current_close > ma7
    above14 = current_close > ma14
    above21 = current_close > ma21
    below7 = current_close < ma7
    below14 = current_close < ma14
    below21 = current_close < ma21

    tier = None
    if above7 and above14 and above21 and macd_direction == "bullish":
        tier = "super_buy"
    elif above7 and above14:
        tier = "strong_buy"
    elif below7 and below14 and below21 and macd_direction == "bearish":
        tier = "super_sell"
    elif below7 and below14:
        tier = "strong_sell"
    elif below7:
        tier = "sell"

    prev_tier = _last_15m_tier.get(symbol)
    _last_15m_tier[symbol] = tier

    if tier is None or tier == prev_tier:
        return

    labels = {
        "super_buy": ("🚀 *SÜPER AL*", "MA7, MA14, MA21 üzerinde + MACD yukarı kesişim"),
        "strong_buy": ("🟢 *GÜÇLÜ AL*", "MA7 ve MA14 üzerinde"),
        "sell": ("🔴 *SAT*", "MA7 altında kapanış"),
        "strong_sell": ("🔻 *GÜÇLÜ SAT*", "MA7 ve MA14 altında"),
        "super_sell": ("💥 *SÜPER SAT*", "MA7, MA14, MA21 altında + MACD aşağı kesişim"),
    }
    title, reason = labels[tier]

    msg = (
        f"{title} — {symbol} (15dk)\n"
        f"{reason}\n"
        f"Fiyat: ${current_close:,.4f}  |  MA7: ${ma7:,.4f}  MA14: ${ma14:,.4f}  MA21: ${ma21:,.4f}\n"
        f"{_format_volume_line(volumes)}"
    )
    send_telegram_message(msg)
