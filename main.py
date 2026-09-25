"""
Basit Whale/MA7 Bot
Kural: 5 dakikalık grafikte fiyat MA7 üzerine çıktığında Telegram'a
AL sinyali + hacim bilgisi gönderir.
Sadece Bybit'te en çok yükselen ilk 20 coin izlenir.
Tek dosya, tek bağımlılık (requests) - kurulumu ve bakımı basit olsun diye.
"""

import os
import time

import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# api.bybit.com bazı bulut sunucu bölgelerinden (Railway ABD dahil) 403 ile
# reddedebiliyor. Bybit'in resmi alternatif adresi api.bytick.com aynı veriyi
# verir ve bu kısıtlamaya takılmaz.
BYBIT_REST_BASE = "https://api.bytick.com"

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

MA_PERIOD = 7
GAINERS_LIMIT = 20
CHECK_INTERVAL_SECONDS = 300       # 5 dakikada bir kontrol
GAINERS_REFRESH_EVERY_N_LOOPS = 3  # yükselenler listesi ~15 dakikada bir yenilensin

_last_state = {}  # {symbol: "above" | "below"} - spam önleme için


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


def fetch_top_gainers(limit=GAINERS_LIMIT):
    """Bybit'te 24 saatte en çok yükselen ilk `limit` USDT çiftini döndürür."""
    url = f"{BYBIT_REST_BASE}/v5/market/tickers"
    resp = requests.get(url, params={"category": "spot"}, headers=REQUEST_HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    gainers = []
    for item in data.get("result", {}).get("list", []):
        symbol = item.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue
        try:
            pct = float(item.get("price24hPcnt", 0)) * 100
        except (TypeError, ValueError):
            continue
        if pct > 0:
            gainers.append({"symbol": symbol, "change_pct": pct})

    gainers.sort(key=lambda x: x["change_pct"], reverse=True)
    return [g["symbol"] for g in gainers[:limit]]


def fetch_5m_closes_and_volumes(symbol, limit=30):
    """Bybit'ten son N adet 5 dakikalık mumun kapanış fiyatını ve hacmini çeker."""
    url = f"{BYBIT_REST_BASE}/v5/market/kline"
    params = {"category": "spot", "symbol": symbol, "interval": "5", "limit": limit}
    resp = requests.get(url, params=params, headers=REQUEST_HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    klines = data.get("result", {}).get("list", [])
    klines.reverse()  # eskiden yeniye sırala
    closes = [float(k[4]) for k in klines]
    volumes = [float(k[6]) for k in klines]  # USDT cinsinden mum hacmi
    return closes, volumes


def calculate_sma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def check_symbol(symbol):
    """Bir coin için MA7 durumunu kontrol eder, üzerine yeni çıktıysa bildirim gönderir."""
    try:
        closes, volumes = fetch_5m_closes_and_volumes(symbol)
    except requests.RequestException as e:
        print(f"[HATA] {symbol} verisi çekilemedi: {e}")
        return

    ma7 = calculate_sma(closes, MA_PERIOD)
    if ma7 is None:
        return

    current_close = closes[-1]
    current_volume = volumes[-1]

    state = "above" if current_close > ma7 else "below"
    prev_state = _last_state.get(symbol)
    _last_state[symbol] = state

    # Sadece "below"dan "above"a yeni geçtiğinde bildir (spam olmasın)
    if state == "above" and prev_state != "above":
        msg = (
            f"🟢 *AL* — {symbol} (5dk)\n"
            f"Fiyat MA7 üzerine çıktı: ${current_close:,.4f} > MA7: ${ma7:,.4f}\n"
            f"Hacim: ${current_volume:,.0f}"
        )
        send_telegram_message(msg)
        print(f"[SİNYAL] {msg}")


def main():
    send_telegram_message("🤖 Basit MA7 Bot başlatıldı.")
    gainers = []
    loop_count = 0

    while True:
        if loop_count % GAINERS_REFRESH_EVERY_N_LOOPS == 0:
            try:
                gainers = fetch_top_gainers()
                print(f"[TARAMA] {len(gainers)} yükselen coin bulundu: {gainers}")
            except requests.RequestException as e:
                print(f"[HATA] Yükselen coin taraması başarısız: {e}")

        for symbol in gainers:
            check_symbol(symbol)
            time.sleep(0.3)  # Bybit rate limit'e takılmamak için

        loop_count += 1
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
