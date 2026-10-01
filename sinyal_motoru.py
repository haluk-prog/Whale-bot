"""
KRİPTO SİNYAL MOTORU - Backtest iskeleti (15dk-1s, dengeli risk)

Akış: Rejim(BTC>SMA200, 4s) -> Trend(EMA20/50/200) -> Momentum(RSI+MACD)
      -> Breakout(20 bar) -> Hacim -> ATR filtresi -> Puan(0-100) -> LONG/SHORT/HOLD
Çıkış: ATR stop + Chandelier trailing + TP(R katı) + zaman stopu

Kullanım:
  python sinyal_motoru.py --synthetic            # boru hattı testi (anlamsız sonuç)
  python sinyal_motoru.py --csv ETH_1h.csv --btc-csv BTC_1h.csv
  python sinyal_motoru.py --csv ETH_1h.csv --btc-csv BTC_1h.csv --wf   # walk-forward
CSV kolonları: timestamp,open,high,low,close,volume
Sinyal bar KAPANIŞINDA üretilir, işlem SONRAKİ bar açılışında yapılır (lookahead yok).
"""
import argparse
from dataclasses import dataclass, replace
import numpy as np
import pandas as pd


@dataclass
class Config:
    threshold: float = 60
    require_breakout: bool = True     # puan ne olursa olsun kırılım şart
    breakout_n: int = 20
    atr_n: int = 14
    atr_lo: float = 0.15              # ATR yüzdelik filtre (sıkışma altı)
    atr_hi: float = 0.92              # (aşırı volatilite üstü)
    vol_rank_win: int = 500
    stop_mult: float = 2.0
    trail_mult: float = 3.0           # Chandelier
    tp_r: float = 2.5                 # take-profit (R katı)
    max_hold: int = 72                # bar (1s'te 3 gün)
    cooldown: int = 6                 # çıkış sonrası bekleme (bar)
    risk_per_trade: float = 0.01      # sermayenin %1'i
    max_leverage: float = 3.0
    fee: float = 0.0005               # taraf başına %0.05
    slippage: float = 0.0002
    initial: float = 10_000.0


# ---------------- İndikatörler ----------------
def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def rsi(c, n=14):
    d = c.diff()
    up, dn = d.clip(lower=0), -d.clip(upper=0)
    ru = up.ewm(alpha=1 / n, adjust=False).mean()
    rd = dn.ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + ru / rd.replace(0, np.nan))

def atr(df, n=14):
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()

def macd_hist(c):
    m = ema(c, 12) - ema(c, 26)
    return m - ema(m, 9)


# ---------------- Rejim ----------------
def regime(btc: pd.DataFrame, index) -> pd.Series:
    """+1: BTC>SMA200(4s), -1: altında, 0: veri yok. Kapanmış 4s mumu kullanılır."""
    h4 = btc["close"].resample("4h").last().dropna()
    sma = h4.rolling(200).mean()
    r = pd.Series(np.where(h4 > sma, 1, -1), index=h4.index).where(sma.notna(), 0)
    r = r.shift(1)  # lookahead engeli
    return r.reindex(index, method="ffill").fillna(0)


# ---------------- Puanlama ----------------
def build_signals(df: pd.DataFrame, reg: pd.Series, cfg: Config):
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
    r, mh = rsi(c), macd_hist(c)
    a = atr(df, cfg.atr_n)
    rank = (a / c).rolling(cfg.vol_rank_win, min_periods=100).rank(pct=True)
    vol_ok = (rank >= cfg.atr_lo) & (rank <= cfg.atr_hi)
    hh = h.rolling(cfg.breakout_n).max().shift(1)
    ll = l.rolling(cfg.breakout_n).min().shift(1)
    brk_l, brk_s = c > hh, c < ll
    rv = v / v.rolling(20).mean()
    vol_pts = np.select([rv >= 1.0, rv >= 0.7], [15, 7], 0)

    def side(up: bool):
        s = 1 if up else -1
        reg_p = 15 * (reg == s)
        full = (e20 > e50) & (e50 > e200) if up else (e20 < e50) & (e50 < e200)
        part = (e20 > e50) if up else (e20 < e50)
        trend_p = np.select([full, part], [20, 8], 0)
        if up:
            rsi_p = np.select([(r >= 50) & (r <= 70), (r > 70) & (r <= 78)], [10, 4], 0)
            macd_p = np.select([(mh > 0) & (mh > mh.shift(1)), mh > 0], [10, 5], 0)
        else:
            rsi_p = np.select([(r >= 30) & (r <= 50), (r >= 22) & (r < 30)], [10, 4], 0)
            macd_p = np.select([(mh < 0) & (mh < mh.shift(1)), mh < 0], [10, 5], 0)
        brk_p = 20 * (brk_l if up else brk_s)
        return (reg_p + trend_p + rsi_p + macd_p + brk_p + vol_pts + 10 * vol_ok).astype(float)

    ls, ss = side(True), side(False)
    return ls.values, ss.values, brk_l.values, brk_s.values, vol_ok.values, a.values


def entry_flags(ls, ss, brk_l, brk_s, vol_ok, cfg: Config):
    gate_l = (brk_l if cfg.require_breakout else True) & vol_ok
    gate_s = (brk_s if cfg.require_breakout else True) & vol_ok
    long_sig = (ls >= cfg.threshold) & gate_l & (ls > ss)
    short_sig = (ss >= cfg.threshold) & gate_s & (ss > ls)
    return long_sig, short_sig


# ---------------- Backtest ----------------
def backtest(df, cfg: Config, long_sig, short_sig, atr_arr, start=0, end=None):
    o, h, l, c = (df[k].values for k in ("open", "high", "low", "close"))
    end = end or len(df)
    eq, pos = cfg.initial, 0
    pending, cool_until = 0, -1
    curve = np.full(end - start, cfg.initial)
    trades = []
    entry = stop = tp = qty = risk_amt = extreme = 0.0
    t_in = 0

    def close_trade(i, px, reason):
        nonlocal eq, pos, cool_until
        px = px * (1 - cfg.slippage * pos)
        pnl = (px - entry) * pos * qty - cfg.fee * qty * (entry + px)
        eq += pnl
        trades.append(dict(entry_time=df.index[t_in], exit_time=df.index[i],
                           side="LONG" if pos == 1 else "SHORT", entry=entry, exit=px,
                           pnl=pnl, R=pnl / risk_amt, bars=i - t_in, reason=reason))
        pos, cool_until = 0, i + cfg.cooldown

    for i in range(max(start, 1), end):
        # 1) bekleyen giriş -> bu barın açılışı
        if pos == 0 and pending != 0 and i > cool_until:
            a = atr_arr[i - 1]
            if np.isfinite(a) and a > 0:
                pos = pending
                entry = o[i] * (1 + cfg.slippage * pos)
                dist = cfg.stop_mult * a
                risk_amt = eq * cfg.risk_per_trade
                qty = min(risk_amt / dist, eq * cfg.max_leverage / entry)
                risk_amt = qty * dist           # kaldıraç sınırı varsa gerçek risk
                stop = entry - pos * dist
                tp = entry + pos * cfg.tp_r * dist
                extreme, t_in = entry, i
        pending = 0

        # 2) açık pozisyon yönetimi (aynı barda stop & TP -> stop öncelikli)
        if pos != 0:
            hit = False
            if pos == 1:
                if o[i] <= stop: close_trade(i, o[i], "stop-gap"); hit = True
                elif l[i] <= stop: close_trade(i, stop, "stop"); hit = True
                elif h[i] >= tp: close_trade(i, tp, "tp"); hit = True
            else:
                if o[i] >= stop: close_trade(i, o[i], "stop-gap"); hit = True
                elif h[i] >= stop: close_trade(i, stop, "stop"); hit = True
                elif l[i] <= tp: close_trade(i, tp, "tp"); hit = True
            if not hit and i - t_in >= cfg.max_hold:
                close_trade(i, c[i], "time"); hit = True
            if not hit:  # Chandelier: sadece lehe ratchet
                a = atr_arr[i]
                if pos == 1:
                    extreme = max(extreme, h[i]); stop = max(stop, extreme - cfg.trail_mult * a)
                else:
                    extreme = min(extreme, l[i]); stop = min(stop, extreme + cfg.trail_mult * a)

        # 3) equity (açık pozisyon mark-to-market)
        curve[i - start] = eq + (pos * (c[i] - entry) * qty if pos else 0.0)

        # 4) sinyal (bar kapanışı) -> sonraki barda giriş
        if pos == 0 and i >= cool_until:
            pending = 1 if long_sig[i] else (-1 if short_sig[i] else 0)

    if pos != 0:
        close_trade(end - 1, c[end - 1], "eod")
        curve[-1] = eq
    return pd.DataFrame(trades), pd.Series(curve, index=df.index[start:end])


# ---------------- Metrikler ----------------
def metrics(trades: pd.DataFrame, curve: pd.Series, cfg: Config) -> dict:
    if trades.empty:
        return dict(trades=0)
    step = curve.index.to_series().diff().median()
    bpy = pd.Timedelta("365D") / step
    ret = curve.pct_change().fillna(0)
    dd = (curve / curve.cummax() - 1).min()
    w, lo = trades[trades.pnl > 0], trades[trades.pnl <= 0]
    pf = w.pnl.sum() / abs(lo.pnl.sum()) if len(lo) and lo.pnl.sum() != 0 else np.inf
    yrs = len(curve) / bpy
    return dict(
        trades=len(trades), net_return=f"{curve.iloc[-1] / cfg.initial - 1:.1%}",
        cagr=f"{(curve.iloc[-1] / cfg.initial) ** (1 / max(yrs, 1e-9)) - 1:.1%}",
        max_dd=f"{dd:.1%}", sharpe=round(ret.mean() / ret.std() * np.sqrt(bpy), 2) if ret.std() > 0 else 0,
        win_rate=f"{len(w) / len(trades):.1%}", profit_factor=round(pf, 2),
        expectancy_R=round(trades.R.mean(), 3), avg_bars=round(trades.bars.mean(), 1),
        long_short=f"{(trades.side == 'LONG').sum()}/{(trades.side == 'SHORT').sum()}")


def run(df, btc, cfg: Config):
    reg = regime(btc, df.index)
    ls, ss, bl, bs, vok, a = build_signals(df, reg, cfg)
    lsig, ssig = entry_flags(ls, ss, bl, bs, vok, cfg)
    tr, cv = backtest(df, cfg, lsig, ssig, a)
    return tr, cv, metrics(tr, cv, cfg)


# ---------------- Walk-forward ----------------
def walk_forward(df, btc, cfg: Config, thresholds=(50, 55, 60, 65, 70, 75),
                 train_bars=4000, test_bars=1000, min_trades=20):
    reg = regime(btc, df.index)
    ls, ss, bl, bs, vok, a = build_signals(df, reg, cfg)
    oos, rows = [], []
    s = 300  # indikatör ısınması
    while s + train_bars + test_bars <= len(df):
        tr_end, te_end = s + train_bars, s + train_bars + test_bars
        best, best_val = cfg.threshold, -np.inf
        for th in thresholds:
            c2 = replace(cfg, threshold=th)
            lsig, ssig = entry_flags(ls, ss, bl, bs, vok, c2)
            t, _ = backtest(df, c2, lsig, ssig, a, s, tr_end)
            if len(t) >= min_trades and t.R.mean() > best_val:
                best, best_val = th, t.R.mean()
        c2 = replace(cfg, threshold=best)
        lsig, ssig = entry_flags(ls, ss, bl, bs, vok, c2)
        t, _ = backtest(df, c2, lsig, ssig, a, tr_end, te_end)
        oos.append(t)
        rows.append(dict(test_start=df.index[tr_end], threshold=best,
                         trades=len(t), exp_R=round(t.R.mean(), 3) if len(t) else np.nan))
        s += test_bars
    allt = pd.concat(oos, ignore_index=True) if oos else pd.DataFrame()
    return pd.DataFrame(rows), allt


# ---------------- Veri ----------------
def load_csv(path):
    d = pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp").sort_index()
    return d[["open", "high", "low", "close", "volume"]].astype(float)

def fetch_ccxt(symbol="ETH/USDT", tf="1h", bars=20000):  # pip install ccxt
    import ccxt
    ex, since, out = ccxt.binance(), None, []
    ms = ex.parse_timeframe(tf) * 1000
    since = ex.milliseconds() - bars * ms
    while len(out) < bars:
        b = ex.fetch_ohlcv(symbol, tf, since=since, limit=1000)
        if not b: break
        out += b; since = b[-1][0] + ms
    d = pd.DataFrame(out, columns=["timestamp", "open", "high", "low", "close", "volume"])
    d["timestamp"] = pd.to_datetime(d["timestamp"], unit="ms")
    return d.set_index("timestamp")

def synthetic(n=30000, seed=7):
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.choice([-1, 0, 1], n // 1500 + 1) * 2e-4, 1500)[:n]
    vol = 0.004 * np.exp(np.cumsum(rng.normal(0, 0.02, n)) * 0.2)
    r = drift + vol * rng.standard_normal(n)
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 2)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 2)))
    v = rng.lognormal(5, 0.4, n) * (1 + 40 * np.abs(r))
    idx = pd.date_range("2023-01-01", periods=n, freq="1h")
    return pd.DataFrame(dict(open=o, high=hi, low=lo, close=c, volume=v), index=idx)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv"); ap.add_argument("--btc-csv")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--wf", action="store_true")
    ap.add_argument("--threshold", type=float, default=60)
    a = ap.parse_args()
    cfg = Config(threshold=a.threshold)
    if a.synthetic:
        df = synthetic(); btc = df
    else:
        df = load_csv(a.csv); btc = load_csv(a.btc_csv) if a.btc_csv else df
    if a.wf:
        folds, allt = walk_forward(df, btc, cfg)
        print(folds.to_string(index=False))
        if len(allt):
            print("\nOOS toplam: işlem", len(allt), "| expectancy R", round(allt.R.mean(), 3),
                  "| kazanma", f"{(allt.pnl > 0).mean():.1%}")
    else:
        tr, cv, m = run(df, btc, cfg)
        for k, v in m.items(): print(f"{k:>14}: {v}")
        tr.to_csv("trades.csv", index=False)
