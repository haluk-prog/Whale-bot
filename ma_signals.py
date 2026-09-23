"""
Whale Tracking Bot - MA sinyal modülü (basitleştirilmiş)

Kurallar:
  5 dk    : Fiyat MA7 üzerine çıkarsa                 -> AL
  5 dk    : Fiyat MA7 ve MA14 üzerindeyse              -> GÜÇLÜ AL
  5 dk    : Fiyat MA7 altında kapanırsa                 -> SAT
  5 dk    : Fiyat MA7 ve MA14 altındaysa                -> GÜÇLÜ SAT
  Günlük  : Fiyat MA50 üzerinde/altında                 -> bilgi (info)

Sadece borsada en çok yükselen ilk 20 coin izlenir (hacimden bağımsız).
Her mesajda ilgili mumun hacim bilgisi de paylaşılır.
Spam olmasın diye durum değişmediği sürece tekrar mesaj gönderilmez.
"""

import requests

from notifier import send_telegram_message

BYBIT_REST_BASE = "https://api.bybit.com"

MA_FAST = 7
MA_MID = 14
MA_DAILY = 50

# Sembol başına son bilinen durumu tutar (spam önleme için, bellek içinde)
_last_5m_tier = {}
_last_daily_state = {}


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


def _format_volume_line(volumes, n_candles=1):
    total_vol = sum(volumes[-n_candles:])
    return f"Hacim: ${total_vol:,.0f}"


async def check_5m_signal(symbol):
    """5 dakikalık grafikte MA7/MA14'e göre AL / GÜÇLÜ AL / SAT / GÜÇLÜ SAT sinyali üretir."""
    try:
        closes, volumes = fetch_closes_and_volumes(symbol, "5", limit=30)
    except requests.RequestException:
        return

    ma7 = calculate_sma(closes, MA_FAST)
    ma14 = calculate_sma(closes, MA_MID)
    if ma7 is None or ma14 is None:
        return

    current_close = closes[-1]
    above7 = current_close > ma7
    above14 = current_close > ma14
    below7 = current_close < ma7
    below14 = current_close < ma14

    tier = None
    if above7 and above14:
        tier = "strong_buy"
    elif above7:
        tier = "buy"
    elif below7 and below14:
        tier = "strong_sell"
    elif below7:
        tier = "sell"

    prev_tier = _last_5m_tier.get(symbol)
    _last_5m_tier[symbol] = tier

    if tier is None or tier == prev_tier:
        return

    labels = {
        "buy": ("🟢 *AL*", "MA7 üzerine çıktı"),
        "strong_buy": ("🚀 *GÜÇLÜ AL*", "MA7 ve MA14 üzerinde"),
        "sell": ("🔴 *SAT*", "MA7 altında kapanış"),
        "strong_sell": ("🔻 *GÜÇLÜ SAT*", "MA7 ve MA14 altında"),
    }
    title, reason = labels[tier]

    msg = (
        f"{title} — {symbol} (5dk)\n"
        f"{reason}\n"
        f"Fiyat: ${current_close:,.4f}  |  MA7: ${ma7:,.4f}  MA14: ${ma14:,.4f}\n"
        f"{_format_volume_line(volumes)}"
    )
    send_telegram_message(msg)


async def check_daily_signal(symbol):
    """Günlük grafikte fiyatın MA50'nin üzerinde/altında olduğunu bildirir (bilgi amaçlı)."""
    try:
        closes, volumes = fetch_closes_and_volumes(symbol, "D", limit=60)
    except requests.RequestException:
        return

    ma50 = calculate_sma(closes, MA_DAILY)
    if ma50 is None:
        return

    current_close = closes[-1]
    state = "above" if current_close > ma50 else "below"
    prev_state = _last_daily_state.get(symbol)
    _last_daily_state[symbol] = state

    if state == prev_state:
        return

    if state == "above":
        title = "📈 *Günlük MA50 Üzerinde*"
        reason = "Uzun vadeli trend yukarı yönlü"
    else:
        title = "📉 *Günlük MA50 Altında*"
        reason = "Uzun vadeli trend aşağı yönlü"

    msg = (
        f"{title} — {symbol} (1G)\n"
        f"{reason}\n"
        f"Fiyat: ${current_close:,.4f}  |  MA50: ${ma50:,.4f}\n"
        f"{_format_volume_line(volumes)}"
    )
    send_telegram_message(msg)
