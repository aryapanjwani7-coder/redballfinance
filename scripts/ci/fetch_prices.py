import json, os, sys, datetime as dt, math
from pathlib import Path

import pandas as pd
import numpy as np
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
QUOTES = DATA / "quotes"
QUOTES.mkdir(parents=True, exist_ok=True)

stocks_json = DATA / "stocks.json"
tx_json = DATA / "transactions.json"  # optional

if not stocks_json.exists():
    print("ERROR: data/stocks.json not found.", file=sys.stderr)
    sys.exit(1)

with open(stocks_json, "r", encoding="utf-8") as f:
    stocks = json.load(f)

symbols = []
meta = []
for s in stocks:
    sym = s.get("symbol") or s.get("ticker")
    if not sym:
        continue
    symbols.append(sym)
    meta.append({
        "symbol": sym,
        "buy_date": s.get("buy_date"),
        "qty": s.get("qty", 0)
    })

# --- Fetch historical prices (max 3y daily; adjust if you want) ---
start = (dt.date.today() - dt.timedelta(days=365*3+30)).isoformat()
end = dt.date.today().isoformat()

# yfinance can fetch multiple tickers but we also want per-symbol files
for sym in symbols:
    try:
        ticker = yf.Ticker(sym)
        hist = ticker.history(interval="1d", start=start, end=end, auto_adjust=False)
        if hist.empty:
            print(f"WARN: no data for {sym}")
            continue
        # prefer 'Adj Close' if present
        if "Adj Close" in hist.columns and not hist["Adj Close"].isna().all():
            close = hist["Adj Close"]
        else:
            close = hist["Close"]
        df = pd.DataFrame({
            "date": close.index.tz_localize(None).date.astype(str),
            "close": close.round(6)
        })
        out = QUOTES / f"{sym}.json"
        df.to_json(out, orient="records", force_ascii=False)
        print(f"wrote {out.relative_to(ROOT)}")
    except Exception as e:
        print(f"ERROR fetching {sym}: {e}", file=sys.stderr)

# --- Build NAV time series ---
def load_quotes(sym):
    f = QUOTES / f"{sym}.json"
    if not f.exists():
        return pd.DataFrame(columns=["date","close"])
    df = pd.read_json(f)
    return df

# Position sizing approach:
# 1) If transactions.json exists => compute daily holdings by cum-summing qty per symbol by date
# 2) Else use stocks.json qty starting from buy_date

dates = set()
price_map = {}  # sym -> df(date, close)

for sym in symbols:
    qdf = load_quotes(sym)
    price_map[sym] = qdf
    dates |= set(qdf["date"].unique())

if not dates:
    print("No quotes fetched; skipping NAV.")
    sys.exit(0)

all_dates = pd.Series(sorted(list(dates)))

# build holdings by date
holdings = {sym: pd.Series(0, index=all_dates) for sym in symbols}

if tx_json.exists():
    tx = pd.read_json(tx_json)
    # normalize
    tx = tx[tx["symbol"].isin(symbols)]
    tx["date"] = pd.to_datetime(tx["date"]).dt.date.astype(str)
    for sym in symbols:
        h = pd.Series(0, index=all_dates, dtype=float)
        sym_tx = tx[tx["symbol"] == sym].sort_values("date")
        for _, row in sym_tx.iterrows():
            # add qty from that date onward
            h.loc[h.index >= row["date"]] += float(row["qty"])
        holdings[sym] = h
else:
    # stocks.json route
    for m in meta:
        sym = m["symbol"]; qty = float(m.get("qty", 0))
        b = m.get("buy_date")
        if not b or qty == 0:
            continue
        h = pd.Series(0, index=all_dates, dtype=float)
        h.loc[h.index >= b] = qty
        holdings[sym] = h

# build aligned price frames with forward fill
values = pd.Series(0.0, index=all_dates, dtype=float)
for sym in symbols:
    qdf = price_map[sym]
    if qdf.empty:
        continue
    s = qdf.set_index("date")["close"].reindex(all_dates).ffill()
    qty = holdings[sym]
    values += (s * qty)

# NAV index (100 at first non-zero value)
first_idx = values.ne(0).idxmax()
base = values.loc[first_idx] if first_idx in values.index and values.loc[first_idx] != 0 else None

nav = pd.DataFrame({
    "date": all_dates,
    "value": values.round(6)
})

if base and base > 0:
    nav["nav_index"] = (values / base * 100.0).round(4)
else:
    nav["nav_index"] = np.nan

# write nav.json
out_nav = DATA / "nav.json"
nav.to_json(out_nav, orient="records", force_ascii=False)
print(f"wrote {out_nav.relative_to(ROOT)}")
