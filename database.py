"""
Whale Tracking Bot - Veritabanı katmanı
SQLite kullanıyoruz; tek dosya, kurulum gerektirmez, kolayca Postgres'e taşınabilir.
"""

import sqlite3
import time
from contextlib import contextmanager

from config import DB_PATH


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS whale_transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tx_hash TEXT,
                symbol TEXT,
                amount REAL,
                amount_usd REAL,
                from_type TEXT,
                to_type TEXT,
                direction TEXT,       -- 'to_exchange' | 'from_exchange' | 'wallet_to_wallet'
                timestamp INTEGER,
                created_at INTEGER DEFAULT (strftime('%s','now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_flow (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                price REAL,
                qty REAL,
                quote_qty REAL,
                is_buyer_maker INTEGER,   -- 1 = satıcı piyasaya vurdu (satış baskısı), 0 = alıcı vurdu
                timestamp INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts_sent (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_type TEXT,
                symbol TEXT,
                message TEXT,
                created_at INTEGER DEFAULT (strftime('%s','now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_flow_symbol_ts ON trade_flow(symbol, timestamp)")
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def insert_whale_transfer(tx):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO whale_transfers
               (tx_hash, symbol, amount, amount_usd, from_type, to_type, direction, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tx["tx_hash"], tx["symbol"], tx["amount"], tx["amount_usd"],
                tx["from_type"], tx["to_type"], tx["direction"], tx["timestamp"],
            ),
        )
        conn.commit()


def insert_trade(symbol, price, qty, quote_qty, is_buyer_maker, timestamp):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO trade_flow (symbol, price, qty, quote_qty, is_buyer_maker, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (symbol, price, qty, quote_qty, int(is_buyer_maker), timestamp),
        )
        conn.commit()


def get_recent_trade_stats(symbol, window_seconds):
    """Belirtilen pencere içindeki toplam alım/satım hacmini döndürür (USD bazında)."""
    cutoff = int(time.time()) - window_seconds
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT is_buyer_maker, SUM(quote_qty)
               FROM trade_flow
               WHERE symbol = ? AND timestamp >= ?
               GROUP BY is_buyer_maker""",
            (symbol, cutoff),
        )
        rows = dict(cur.fetchall())
    # is_buyer_maker = 1 -> satış baskısı (taker sold), 0 -> alış baskısı (taker bought)
    sell_volume = rows.get(1, 0.0) or 0.0
    buy_volume = rows.get(0, 0.0) or 0.0
    return buy_volume, sell_volume


def get_average_volume(symbol, window_seconds, lookback_windows=6):
    """Karşılaştırma için geçmiş pencerelerin ortalama hacmini hesaplar."""
    cutoff = int(time.time()) - (window_seconds * lookback_windows)
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT SUM(quote_qty) FROM trade_flow WHERE symbol = ? AND timestamp >= ?""",
            (symbol, cutoff),
        )
        total = cur.fetchone()[0] or 0.0
    return total / lookback_windows if lookback_windows else 0.0


def prune_old_trades(max_age_seconds=3600):
    cutoff = int(time.time()) - max_age_seconds
    with get_conn() as conn:
        conn.execute("DELETE FROM trade_flow WHERE timestamp < ?", (cutoff,))
        conn.commit()


def log_alert(alert_type, symbol, message):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO alerts_sent (alert_type, symbol, message) VALUES (?, ?, ?)",
            (alert_type, symbol, message),
        )
        conn.commit()
