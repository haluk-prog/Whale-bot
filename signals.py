"""
Whale Tracking Bot - Sinyal ve tarama modülü

Bu modül üç işi yapar:
  1) Bybit'teki TÜM USDT spot çiftlerini tarar, hacme göre iki gruba ayırır
     (yüksek hacimli / düşük hacimli)
  2) RSI ve MACD indikatörlerini harici kütüphane kullanmadan hesaplar
  3) Saatlik mumlarda RSI+MACD yükseliş kesişimi olup olmadığını kontrol eder
"""

import requests

from config import (
    HIGH_VOLUME_USD_THRESHOLD,
    LOW_VOLUME_WEEKLY_USD_THRESHOLD,
    MAX_HIGH_VOLUME_SYMBOLS,
    RSI_PERIOD,
    MACD_FAST,
    MACD_SLOW,
    MACD_SIGNAL,
)

BYBIT_REST_BASE = "https://api.bybit.com"


# ---------------------------------------------------------------------------
# COIN EVRENİ TARAMA
# ---------------------------------------------------------------------------

def fetch_all_usdt_symbols_with_volume():
    """
    Bybit spot piyasasındaki tüm USDT çiftlerini ve 24 saatlik hacimlerini çeker.
    Dönüş: [{"symbol": "BTCUSDT", "volume_24h_usd": 12345678.0}, ...]
    """
    url = f"{BYBIT_REST_BASE}/v5/market/tickers"
    resp = requests.get(url, params={"category": "spot"}, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for item in data.get("result", {}).get("list", []):
        symbol = item.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue
        try:
            turnover = float(item.get("turnover24h", 0))
        except (TypeError, ValueError):
            turnover = 0.0
        results.append({"symbol": symbol, "volume_24h_usd": turnover})
    return results


def classify_symbols(all_symbols):
    """
    Coinleri hacme göre iki gruba ayırır:
      - high_volume: 24 saatlik hacmi eşik üzerinde -> WebSocket ile canlı izlenir
      - low_volume: tahmini haftalık hacmi eşik üzerinde -> periyodik REST kontrolü
    Çok düşük hacimli / neredeyse ölü coinler tamamen elenir (hiç izlenmez).
    """
    high_volume_items = []
    low_volume = []

    for item in all_symbols:
        vol_24h = item["volume_24h_usd"]
        # Basit tahmin: gerçek 7 günlük toplamı çekmek yerine 24s hacmi 7 ile çarpıyoruz.
        # Bu kesin değil ama filtreleme amacı için yeterli.
        vol_weekly_est = vol_24h * 7

        if vol_24h >= HIGH_VOLUME_USD_THRESHOLD:
            high_volume_items.append(item)
        elif vol_weekly_est >= LOW_VOLUME_WEEKLY_USD_THRESHOLD:
            low_volume.append(item["symbol"])
        # else: çok düşük hacimli, tamamen elenir

    # En yüksek hacimliden başlayarak sırala, kaynak kullanımı için tavana kes
    high_volume_sorted = sorted(high_volume_items, key=lambda i: i["volume_24h_usd"], reverse=True)
    high_volume_symbols = [i["symbol"] for i in high_volume_sorted[:MAX_HIGH_VOLUME_SYMBOLS]]

    return high_volume_symbols, low_volume


# ---------------------------------------------------------------------------
# TEKNİK İNDİKATÖRLER (manuel hesaplama, harici kütüphane gerekmez)
# ---------------------------------------------------------------------------

def calculate_ema(values, period):
    ema = [values[0]]
    multiplier = 2 / (period + 1)
    for price in values[1:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    return ema


def calculate_rsi(closes, period=RSI_PERIOD):
    if len(closes) < period + 1:
        return None

    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_macd(closes, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL):
    if len(closes) < slow + signal:
        return None, None, None

    ema_fast = calculate_ema(closes, fast)
    ema_slow = calculate_ema(closes, slow)
    # İki EMA listesi farklı uzunlukta olabilir, sondan hizalıyoruz
    min_len = min(len(ema_fast), len(ema_slow))
    macd_line_full = [ema_fast[-min_len:][i] - ema_slow[-min_len:][i] for i in range(min_len)]
    signal_line_full = calculate_ema(macd_line_full, signal)

    macd_now = macd_line_full[-1]
    signal_now = signal_line_full[-1]
    histogram = macd_now - signal_now
    return macd_now, signal_now, histogram


def fetch_hourly_closes(symbol, limit=150):
    """Bybit'ten son N saatlik kapanış fiyatını (eskiden yeniye sıralı) çeker."""
    url = f"{BYBIT_REST_BASE}/v5/market/kline"
    params = {"category": "spot", "symbol": symbol, "interval": "60", "limit": limit}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    klines = data.get("result", {}).get("list", [])
    klines.reverse()  # Bybit en yeniyi en üstte döndürür, kronolojik sıraya çeviriyoruz
    closes = [float(k[4]) for k in klines]
    return closes


def check_bullish_crossover(symbol):
    """
    Saatlik mumlarda RSI + MACD birlikte yükseliş sinyali verip vermediğini kontrol eder.
    Kural: MACD çizgisi sinyal çizgisini az önce yukarı kesmiş VE RSI 50 üzerinde
    (momentum yukarı yönlü, aşırı satımdan çıkış teyit edilmiş).
    Dönüş: (True/False, detay_dict veya None)
    """
    try:
        closes = fetch_hourly_closes(symbol)
    except requests.RequestException:
        return False, None

    if len(closes) < MACD_SLOW + MACD_SIGNAL + 2:
        return False, None

    macd_now, signal_now, _ = calculate_macd(closes)
    macd_prev, signal_prev, _ = calculate_macd(closes[:-1])
    rsi_now = calculate_rsi(closes)

    if None in (macd_now, signal_now, macd_prev, signal_prev, rsi_now):
        return False, None

    bullish_cross = macd_prev <= signal_prev and macd_now > signal_now
    momentum_ok = rsi_now > 50

    if bullish_cross and momentum_ok:
        return True, {"rsi": rsi_now, "macd": macd_now, "signal": signal_now}
    return False, None
