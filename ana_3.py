"""
================================================================================
M15 Multi-Indicator Low-Noise Trading Bot (OKX üzerinden)
================================================================================
15 dakikalık (M15) zaman diliminde gürültü ve fake-out hareketleri azaltmak
için çoklu teyit mekanizması kullanan trend + momentum tabanlı sinyal botu.

FİLTRELER:
  1. Trend Filtresi      : EMA200 (M15) - fiyat üstündeyse LONG, altındaysa SHORT bölgesi
  2. Üst Zaman Dilimi     : H1 EMA200 ile trend yönü teyidi
  3. Hacim/Maliyet        : Session VWAP'a göre fiyatın konumu
  4. Momentum             : RSI14 + MACD histogram + uyumsuzluk (divergence) taraması
  5. Piyasa Rejimi        : ADX14 > 25 ise trend aktif, değilse sinyal yok (yatay piyasa filtrelenir)
  6. Hacim Teyidi         : Kapanan mumun hacmi, ortalamanın 1.5 katından fazla olmalı

Tüm filtreler AYNI ANDA aynı yönde doğrulanırsa LONG veya SHORT sinyali üretilir.
Sadece OKX'te en çok yükselen ilk 20 USDT çifti izlenir.
Not: Divergence tespiti basitleştirilmiş bir sezgisel (heuristic) yöntemdir,
profesyonel grafik yazılımlarındaki kadar hassas olmayabilir.
================================================================================
"""

import os
import time
from datetime import datetime, timezone

import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

OKX_REST_BASE = "https://www.okx.com"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

GAINERS_LIMIT = 20
CHECK_INTERVAL_SECONDS = 900          # 15 dakika (M15 bar kapanışıyla hizalı)
GAINERS_REFRESH_EVERY_N_LOOPS = 4     # yükselenler listesi ~saatte bir yenilensin

EMA_TREND_PERIOD = 200
RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
ADX_PERIOD = 14
ADX_TREND_THRESHOLD = 25
VOLUME_SPIKE_MULTIPLIER = 1.5
VOLUME_MA_PERIOD = 20
DIVERGENCE_LOOKBACK = 30

_last_signal = {}  # {instId: "long" | "short" | None} - spam önleme için


# ---------------------------------------------------------------------------
# TELEGRAM & VERİ ÇEKME
# ---------------------------------------------------------------------------

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[UYARI] Telegram bilgileri eksik, mesaj gönderilemiyor:", text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except requests.RequestException as e:
        print("[HATA] Telegram mesajı gönderilemedi:", e)


def fetch_candles(inst_id, bar, limit):
    """OKX'ten mum verisi çeker: [{ts, open, high, low, close, vol_quote}, ...] (eskiden yeniye)."""
    url = f"{OKX_REST_BASE}/api/v5/market/candles"
    params = {"instId": inst_id, "bar": bar, "limit": limit}
    resp = requests.get(url, params=params, headers=REQUEST_HEADERS, timeout=15)
    resp.raise_for_status()
    raw = resp.json().get("data", [])
    raw.reverse()  # OKX en yeniyi en üstte döndürür, kronolojik sıraya çeviriyoruz
    return [
        {
            "ts": int(c[0]),
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
            "vol_quote": float(c[6]),  # USDT cinsinden hacim
        }
        for c in raw
    ]


def fetch_top_gainers(limit=GAINERS_LIMIT):
    """OKX'te 24 saatte en çok yükselen ilk `limit` USDT spot çiftini döndürür."""
    url = f"{OKX_REST_BASE}/api/v5/market/tickers"
    resp = requests.get(url, params={"instType": "SPOT"}, headers=REQUEST_HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    gainers = []
    for item in data.get("data", []):
        inst_id = item.get("instId", "")
        if not inst_id.endswith("-USDT"):
            continue
        try:
            last = float(item.get("last", 0))
            open24h = float(item.get("open24h", 0))
        except (TypeError, ValueError):
            continue
        if open24h <= 0:
            continue
        pct = (last - open24h) / open24h * 100
        if pct > 0:
            gainers.append({"instId": inst_id, "change_pct": pct})

    gainers.sort(key=lambda x: x["change_pct"], reverse=True)
    return [g["instId"] for g in gainers[:limit]]


# ---------------------------------------------------------------------------
# İNDİKATÖRLER (manuel hesaplama, harici kütüphane gerekmez)
# ---------------------------------------------------------------------------

def ema_series(values, period):
    if len(values) < period:
        return []
    ema = [sum(values[:period]) / period]
    multiplier = 2 / (period + 1)
    for price in values[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    return ema


def rsi_series(closes, period=RSI_PERIOD):
    if len(closes) < period + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsis = [100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))]

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsis.append(100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss)))

    return rsis


def macd_histogram_series(closes):
    if len(closes) < MACD_SLOW + MACD_SIGNAL:
        return []
    ema_fast = ema_series(closes, MACD_FAST)
    ema_slow = ema_series(closes, MACD_SLOW)
    min_len = min(len(ema_fast), len(ema_slow))
    macd_line = [ema_fast[-min_len:][i] - ema_slow[-min_len:][i] for i in range(min_len)]
    signal_line = ema_series(macd_line, MACD_SIGNAL)
    hist = [macd_line[-len(signal_line):][i] - signal_line[i] for i in range(len(signal_line))]
    return hist


def calculate_adx(candles, period=ADX_PERIOD):
    """Wilder'ın ADX hesaplama yöntemi. Piyasanın trend mi yatay mı olduğunu ölçer."""
    if len(candles) < period * 2:
        return None

    plus_dm, minus_dm, tr = [], [], []
    for i in range(1, len(candles)):
        up_move = candles[i]["high"] - candles[i - 1]["high"]
        down_move = candles[i - 1]["low"] - candles[i]["low"]
        plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0)
        minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0)
        tr.append(max(
            candles[i]["high"] - candles[i]["low"],
            abs(candles[i]["high"] - candles[i - 1]["close"]),
            abs(candles[i]["low"] - candles[i - 1]["close"]),
        ))

    def wilder_smooth(values, period):
        smoothed = [sum(values[:period])]
        for v in values[period:]:
            smoothed.append(smoothed[-1] - (smoothed[-1] / period) + v)
        return smoothed

    tr_smooth = wilder_smooth(tr, period)
    plus_dm_smooth = wilder_smooth(plus_dm, period)
    minus_dm_smooth = wilder_smooth(minus_dm, period)

    plus_di = [100 * (plus_dm_smooth[i] / tr_smooth[i]) if tr_smooth[i] else 0 for i in range(len(tr_smooth))]
    minus_di = [100 * (minus_dm_smooth[i] / tr_smooth[i]) if tr_smooth[i] else 0 for i in range(len(tr_smooth))]

    dx = [
        100 * abs(plus_di[i] - minus_di[i]) / (plus_di[i] + minus_di[i])
        if (plus_di[i] + minus_di[i]) else 0
        for i in range(len(plus_di))
    ]

    if len(dx) < period:
        return None

    adx = sum(dx[:period]) / period
    for d in dx[period:]:
        adx = (adx * (period - 1) + d) / period

    return adx


def calculate_session_vwap(candles):
    """Bugünkü (UTC) mumlardan hacim ağırlıklı ortalama fiyatı (VWAP) hesaplar."""
    if not candles:
        return None

    today = datetime.fromtimestamp(candles[-1]["ts"] / 1000, tz=timezone.utc).date()
    today_candles = [
        c for c in candles
        if datetime.fromtimestamp(c["ts"] / 1000, tz=timezone.utc).date() == today
    ]
    if not today_candles:
        return None

    cum_pv, cum_vol = 0.0, 0.0
    for c in today_candles:
        typical_price = (c["high"] + c["low"] + c["close"]) / 3
        cum_pv += typical_price * c["vol_quote"]
        cum_vol += c["vol_quote"]

    return cum_pv / cum_vol if cum_vol > 0 else None


def find_swing_points(values, window=2):
    """Basit yerel tepe/dip tespiti."""
    peaks, troughs = [], []
    for i in range(window, len(values) - window):
        segment = values[i - window:i + window + 1]
        if values[i] == max(segment):
            peaks.append(i)
        if values[i] == min(segment):
            troughs.append(i)
    return peaks, troughs


def detect_divergence(closes, rsis, lookback=DIVERGENCE_LOOKBACK):
    """Basitleştirilmiş uyumsuzluk (divergence) tespiti: son iki tepe/dip noktasını karşılaştırır."""
    n = min(lookback, len(closes), len(rsis))
    if n < 10:
        return None

    recent_closes = closes[-n:]
    recent_rsis = rsis[-n:]
    peaks, troughs = find_swing_points(recent_closes)

    if len(peaks) >= 2:
        p1, p2 = peaks[-2], peaks[-1]
        if recent_closes[p2] > recent_closes[p1] and recent_rsis[p2] < recent_rsis[p1]:
            return "bearish"

    if len(troughs) >= 2:
        t1, t2 = troughs[-2], troughs[-1]
        if recent_closes[t2] < recent_closes[t1] and recent_rsis[t2] > recent_rsis[t1]:
            return "bullish"

    return None


# ---------------------------------------------------------------------------
# ANA ANALİZ (onay matrisi)
# ---------------------------------------------------------------------------

def analyze_symbol(inst_id):
    try:
        m15 = fetch_candles(inst_id, "15m", 300)
        h1 = fetch_candles(inst_id, "1H", 250)
    except requests.RequestException as e:
        print(f"[HATA] {inst_id} verisi çekilemedi: {e}")
        return None

    if len(m15) < EMA_TREND_PERIOD + 5 or len(h1) < EMA_TREND_PERIOD + 5:
        return None

    closes_m15 = [c["close"] for c in m15]
    closes_h1 = [c["close"] for c in h1]

    ema200_m15_series = ema_series(closes_m15, EMA_TREND_PERIOD)
    ema200_h1_series = ema_series(closes_h1, EMA_TREND_PERIOD)
    if not ema200_m15_series or not ema200_h1_series:
        return None

    ema200_m15 = ema200_m15_series[-1]
    ema200_h1 = ema200_h1_series[-1]
    current_close = closes_m15[-1]

    trend_long = current_close > ema200_m15
    trend_short = current_close < ema200_m15
    h1_trend_long = closes_h1[-1] > ema200_h1
    h1_trend_short = closes_h1[-1] < ema200_h1

    vwap = calculate_session_vwap(m15)
    if vwap is None:
        return None
    vwap_long = current_close > vwap
    vwap_short = current_close < vwap

    rsis = rsi_series(closes_m15)
    hist = macd_histogram_series(closes_m15)
    if len(rsis) < 5 or len(hist) < 2:
        return None

    current_rsi = rsis[-1]
    macd_rising = hist[-1] > hist[-2]
    macd_falling = hist[-1] < hist[-2]
    divergence = detect_divergence(closes_m15, rsis)

    momentum_long = current_rsi > 50 and hist[-1] > 0 and macd_rising and divergence != "bearish"
    momentum_short = current_rsi < 50 and hist[-1] < 0 and macd_falling and divergence != "bullish"

    adx = calculate_adx(m15)
    if adx is None or adx <= ADX_TREND_THRESHOLD:
        return None  # yatay piyasa, sinyal üretilmez

    volumes = [c["vol_quote"] for c in m15]
    if len(volumes) < VOLUME_MA_PERIOD + 1:
        return None
    avg_volume = sum(volumes[-(VOLUME_MA_PERIOD + 1):-1]) / VOLUME_MA_PERIOD
    current_volume = volumes[-1]
    volume_spike = avg_volume > 0 and current_volume > avg_volume * VOLUME_SPIKE_MULTIPLIER

    long_signal = trend_long and h1_trend_long and vwap_long and momentum_long and volume_spike
    short_signal = trend_short and h1_trend_short and vwap_short and momentum_short and volume_spike

    direction = "long" if long_signal else ("short" if short_signal else None)

    return {
        "direction": direction,
        "price": current_close,
        "ema200": ema200_m15,
        "vwap": vwap,
        "rsi": current_rsi,
        "macd_hist": hist[-1],
        "adx": adx,
        "volume": current_volume,
        "avg_volume": avg_volume,
        "h1_trend": "yukarı" if h1_trend_long else "aşağı",
    }


def check_symbol(inst_id):
    result = analyze_symbol(inst_id)
    if result is None:
        return

    direction = result["direction"]
    prev_direction = _last_signal.get(inst_id)
    _last_signal[inst_id] = direction

    if direction is None or direction == prev_direction:
        return

    title = "🟢 *LONG Sinyali*" if direction == "long" else "🔴 *SHORT Sinyali*"

    msg = (
        f"{title} — {inst_id} (M15)\n"
        f"Fiyat: ${result['price']:,.4f}\n"
        f"EMA200: ${result['ema200']:,.4f}  |  VWAP: ${result['vwap']:,.4f}\n"
        f"RSI: {result['rsi']:.1f}  |  MACD Hist: {result['macd_hist']:.5f}\n"
        f"ADX: {result['adx']:.1f} (trend rejimi aktif)\n"
        f"H1 Trend: {result['h1_trend']}\n"
        f"Hacim: ${result['volume']:,.0f}  (ort: ${result['avg_volume']:,.0f})"
    )
    send_telegram_message(msg)
    print(f"[SİNYAL] {msg}")


def main():
    send_telegram_message("🤖 M15 Multi-Indicator Low-Noise Bot başlatıldı (OKX).")
    gainers = []
    loop_count = 0

    while True:
        if loop_count % GAINERS_REFRESH_EVERY_N_LOOPS == 0:
            try:
                gainers = fetch_top_gainers()
                print(f"[TARAMA] {len(gainers)} yükselen coin bulundu: {gainers}")
            except requests.RequestException as e:
                print(f"[HATA] Yükselen coin taraması başarısız: {e}")

        for inst_id in gainers:
            check_symbol(inst_id)
            time.sleep(0.5)  # rate limit'e takılmamak için

        loop_count += 1
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
