"""
Whale Tracking Bot - Otomatik alım/satım modülü (Bybit TESTNET)

ÖNEMLİ: Bu modül Bybit'in TESTNET ortamını kullanır (api-testnet.bybit.com).
Testnet'te kullanılan para SAHTEDİR, gerçek finansal risk yoktur.
Gerçek hesaba (mainnet) geçiş yapılmadan önce stratejinin haftalarca
testnet'te izlenmesi ve sonuçların değerlendirilmesi önerilir.

Bybit v5 API kimlik doğrulaması HMAC-SHA256 imza gerektirir.
"""

import hashlib
import hmac
import time
import json

import requests

from config import (
    BYBIT_TESTNET_API_KEY,
    BYBIT_TESTNET_API_SECRET,
    BYBIT_TESTNET_REST_BASE,
    TRADING_ENABLED,
    POSITION_SIZE_USD,
    STOP_LOSS_PERCENT,
    TAKE_PROFIT_PERCENT,
    MAX_OPEN_POSITIONS,
)
from database import (
    has_open_position,
    open_position,
    get_open_positions,
    close_position,
    get_latest_price,
)
from notifier import send_telegram_message

RECV_WINDOW = "5000"


def _sign_request(params_str, timestamp):
    """Bybit v5 API için HMAC-SHA256 imza üretir."""
    sign_payload = f"{timestamp}{BYBIT_TESTNET_API_KEY}{RECV_WINDOW}{params_str}"
    return hmac.new(
        BYBIT_TESTNET_API_SECRET.encode("utf-8"),
        sign_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _authed_headers(params_str):
    timestamp = str(int(time.time() * 1000))
    signature = _sign_request(params_str, timestamp)
    return {
        "X-BAPI-API-KEY": BYBIT_TESTNET_API_KEY,
        "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-RECV-WINDOW": RECV_WINDOW,
        "X-BAPI-SIGN": signature,
        "Content-Type": "application/json",
    }


def _place_market_order(symbol, side, market_unit_qty):
    """
    Bybit spot piyasasında market emri gönderir.
    side: "Buy" veya "Sell"
    market_unit_qty: Buy için USDT tutarı (quoteCoin), Sell için coin miktarı (baseCoin)
    """
    body = {
        "category": "spot",
        "symbol": symbol,
        "side": side,
        "orderType": "Market",
        "qty": str(market_unit_qty),
    }
    if side == "Buy":
        body["marketUnit"] = "quoteCoin"  # qty, USDT tutarı olarak yorumlanır

    body_str = json.dumps(body)
    headers = _authed_headers(body_str)
    url = f"{BYBIT_TESTNET_REST_BASE}/v5/order/create"

    resp = requests.post(url, headers=headers, data=body_str, timeout=15)
    resp.raise_for_status()
    return resp.json()


def try_open_position(symbol, current_price):
    """
    Bir sinyal geldiğinde çağrılır. Trading kapalıysa hiçbir şey yapmaz.
    Zaten açık pozisyon varsa veya limit dolmuşsa yeni pozisyon açmaz.
    """
    if not TRADING_ENABLED:
        return

    if has_open_position(symbol):
        return

    if len(get_open_positions()) >= MAX_OPEN_POSITIONS:
        return

    try:
        result = _place_market_order(symbol, "Buy", POSITION_SIZE_USD)
    except requests.RequestException as e:
        send_telegram_message(f"⚠️ *Emir Hatası* — {symbol}\nAlım emri gönderilemedi: {e}")
        return

    ret_code = result.get("retCode")
    if ret_code != 0:
        send_telegram_message(
            f"⚠️ *Emir Reddedildi* — {symbol}\n"
            f"Bybit yanıtı: {result.get('retMsg', 'bilinmeyen hata')}"
        )
        return

    qty_bought = POSITION_SIZE_USD / current_price  # yaklaşık miktar
    stop_loss_price = current_price * (1 - STOP_LOSS_PERCENT / 100)
    take_profit_price = current_price * (1 + TAKE_PROFIT_PERCENT / 100)

    open_position(
        symbol=symbol,
        entry_price=current_price,
        qty=qty_bought,
        usd_amount=POSITION_SIZE_USD,
        stop_loss_price=stop_loss_price,
        take_profit_price=take_profit_price,
    )

    msg = (
        f"🟢 *[TESTNET] Pozisyon Açıldı* — {symbol}\n"
        f"Giriş: ${current_price:,.4f}  |  Tutar: ${POSITION_SIZE_USD}\n"
        f"Stop-Loss: ${stop_loss_price:,.4f}  |  Take-Profit: ${take_profit_price:,.4f}"
    )
    send_telegram_message(msg)


def _close_position_market(symbol, qty):
    return _place_market_order(symbol, "Sell", qty)


async def monitor_positions():
    """Açık pozisyonları kontrol eder, TP/SL'ye ulaşanları kapatır."""
    if not TRADING_ENABLED:
        return

    for pos in get_open_positions():
        symbol = pos["symbol"]
        current_price = get_latest_price(symbol)
        if current_price is None:
            continue

        hit_tp = current_price >= pos["take_profit_price"]
        hit_sl = current_price <= pos["stop_loss_price"]

        if not (hit_tp or hit_sl):
            continue

        try:
            _close_position_market(symbol, pos["qty"])
        except requests.RequestException as e:
            send_telegram_message(f"⚠️ *Kapatma Hatası* — {symbol}\nSatış emri gönderilemedi: {e}")
            continue

        pnl_usd = (current_price - pos["entry_price"]) * pos["qty"]
        reason = "take_profit" if hit_tp else "stop_loss"
        close_position(pos["id"], current_price, reason, pnl_usd)

        emoji = "✅" if hit_tp else "🛑"
        reason_tr = "Take-Profit" if hit_tp else "Stop-Loss"
        msg = (
            f"{emoji} *[TESTNET] Pozisyon Kapandı* — {symbol}\n"
            f"Sebep: {reason_tr}\n"
            f"Giriş: ${pos['entry_price']:,.4f}  →  Çıkış: ${current_price:,.4f}\n"
            f"Kâr/Zarar: ${pnl_usd:,.2f}"
        )
        send_telegram_message(msg)
