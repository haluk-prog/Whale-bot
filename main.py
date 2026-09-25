"""
Basit Whale/MA7 Bot (OKX üzerinden)
Kural: 5 dakikalık grafikte fiyat MA7 üzerine çıktığında Telegram'a
AL sinyali + hacim bilgisi gönderir.
En çok yükselen ilk 20 USDT çifti izlenir.

Not: Bybit'in REST API'si Railway'in bulut IP'sinden 403 ile engellendiği
için OKX kullanıyoruz (OKX bu tür bulut IP kısıtlamalarına takılmıyor).
"""

import os
import time

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

MA_PERIOD = 7
GAINERS_LIMIT = 20
CHECK_INTERVAL_SECONDS = 300       # 5 dakikada bir kontrol
GAINERS_REFRESH_EVERY_N_LOOPS = 3  # yükselenler listesi ~15 dakikada bir yenilensin

_last_state = {}  # {instId: "above" | "below"} - spam önleme için


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
    """OKX'te 24 saatte en çok yükselen ilk `limit` USDT spot çiftini döndürür."""
    url = f"{OKX_REST_BASE}/api/v5/market/tickers"
    resp = requests.get(url, params={"instType": "SPOT"}, headers=REQUEST_HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    gainers = []
    for item in data.get("data", []):
        inst_id = item.get("instId", "")  # örn. "BTC-USDT"
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


def fetch_5m_closes_and_volumes(inst_id, limit=30):
    """OKX'ten son N adet 5 dakikalık mumun kapanış fiyatını ve hacmini (USDT) çeker."""
    url = f"{OKX_REST_BASE}/api/v5/market/candles"
    params = {"instId": inst_id, "bar": "5m", "limit": limit}
    resp = requests.get(url, params=params, headers=REQUEST_HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    candles = data.get("data", [])
    candles.reverse()  # OKX en yeniyi en üstte döndürür, kronolojik sıraya çeviriyoruz
    # Her mum: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
    closes = [float(c[4]) for c in candles]
    volumes = [float(c[6]) for c in candles]  # volCcy: USDT cinsinden hacim
    return closes, volumes


def calculate_sma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def check_symbol(inst_id):
    """Bir coin için MA7 durumunu kontrol eder, üzerine yeni çıktıysa bildirim gönderir."""
    try:
        closes, volumes = fetch_5m_closes_and_volumes(inst_id)
    except requests.RequestException as e:
        print(f"[HATA] {inst_id} verisi çekilemedi: {e}")
        return

    ma7 = calculate_sma(closes, MA_PERIOD)
    if ma7 is None or not volumes:
        return

    current_close = closes[-1]
    current_volume = volumes[-1]

    state = "above" if current_close > ma7 else "below"
    prev_state = _last_state.get(inst_id)
    _last_state[inst_id] = state

    # Sadece "below"dan "above"a yeni geçtiğinde bildir (spam olmasın)
    if state == "above" and prev_state != "above":
        msg = (
            f"🟢 *AL* — {inst_id} (5dk)\n"
            f"Fiyat MA7 üzerine çıktı: ${current_close:,.4f} > MA7: ${ma7:,.4f}\n"
            f"Hacim: ${current_volume:,.0f}"
        )
        send_telegram_message(msg)
        print(f"[SİNYAL] {msg}")


def main():
    send_telegram_message("🤖 Basit MA7 Bot başlatıldı (OKX).")
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
            time.sleep(0.3)  # rate limit'e takılmamak için

        loop_count += 1
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main() 
