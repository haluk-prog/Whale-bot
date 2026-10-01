"""
20 COİN TARAYICI  (sinyal_motoru.py ile aynı klasöre koyun)

  python tarayici.py --synthetic            # test
  python tarayici.py --scan                 # Binance'ten çek, şu anki sinyalleri sırala
  python tarayici.py --bt                   # her coin + portföy backtest
Aynı parametreler tüm coinlere uygulanır (coin başına ayar = overfitting).
"""
import argparse
import numpy as np
import pandas as pd
from sinyal_motoru import (Config, build_signals, entry_flags, regime, backtest,
                           metrics, fetch_ccxt, synthetic)

COINS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT",
         "LTC", "BCH", "ATOM", "NEAR", "APT", "ARB", "OP", "INJ", "SUI", "TRX"]
MAX_OPEN = 5          # aynı anda en fazla pozisyon (coinler birbirine korele!)
TF = "1h"


def load_all(synth=False, bars=20000):
    data = {}
    for i, c in enumerate(COINS):
        if synth:
            data[c] = synthetic(seed=100 + i)
        else:
            d = fetch_ccxt(f"{c}/USDT", TF, bars)
            data[c] = d.iloc[:-1]          # son (kapanmamış) mumu at
    return data


def scan(data, cfg):
    btc = data["BTC"]
    rows = []
    for c, df in data.items():
        reg = regime(btc, df.index)
        ls, ss, bl, bs, vok, a = build_signals(df, reg, cfg)
        lsig, ssig = entry_flags(ls, ss, bl, bs, vok, cfg)
        px, atr_ = df["close"].iloc[-1], a[-1]
        side = "LONG" if lsig[-1] else "SHORT" if ssig[-1] else "-"
        d = 1 if side == "LONG" else -1
        rows.append(dict(coin=c, long_puan=ls[-1], short_puan=ss[-1], sinyal=side,
                         fiyat=round(px, 4),
                         stop=round(px - d * cfg.stop_mult * atr_, 4) if side != "-" else None,
                         tp=round(px + d * cfg.tp_r * cfg.stop_mult * atr_, 4) if side != "-" else None))
    t = pd.DataFrame(rows)
    t["en_iyi"] = t[["long_puan", "short_puan"]].max(axis=1)
    return t.sort_values("en_iyi", ascending=False).drop(columns="en_iyi").reset_index(drop=True)


def portfolio_bt(data, cfg):
    btc, all_tr, rows = data["BTC"], [], []
    for c, df in data.items():
        reg = regime(btc, df.index)
        ls, ss, bl, bs, vok, a = build_signals(df, reg, cfg)
        lsig, ssig = entry_flags(ls, ss, bl, bs, vok, cfg)
        tr, cv = backtest(df, cfg, lsig, ssig, a)
        if len(tr):
            tr["coin"] = c; all_tr.append(tr)
        m = metrics(tr, cv, cfg)
        rows.append(dict(coin=c, trades=m.get("trades", 0), expR=m.get("expectancy_R"),
                         pf=m.get("profit_factor"), win=m.get("win_rate"), maxdd=m.get("max_dd")))
    per = pd.DataFrame(rows).sort_values("expR", ascending=False)

    # Portföy: giriş zamanına göre sırala, MAX_OPEN dolduysa işlemi atla
    pool = pd.concat(all_tr).sort_values("entry_time").reset_index(drop=True)
    taken, open_exits = [], []
    for _, t in pool.iterrows():
        open_exits = [x for x in open_exits if x > t.entry_time]
        if len(open_exits) < MAX_OPEN:
            taken.append(t); open_exits.append(t.exit_time)
    pf = pd.DataFrame(taken)
    eq = (1 + cfg.risk_per_trade * pf.sort_values("exit_time").R).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    summary = dict(islem=len(pf), atlanan=len(pool) - len(pf), expectancy_R=round(pf.R.mean(), 3),
                   kazanma=f"{(pf.R > 0).mean():.1%}", net=f"{eq.iloc[-1] - 1:.1%}", max_dd=f"{dd:.1%}")
    return per, summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--bt", action="store_true")
    a = ap.parse_args()
    cfg = Config()
    data = load_all(a.synthetic)
    if a.scan or not a.bt:
        print(scan(data, cfg).head(10).to_string(index=False))
    if a.bt:
        per, s = portfolio_bt(data, cfg)
        print(per.to_string(index=False)); print("\nPORTFÖY:", s)
