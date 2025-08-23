import os, sys, json, time, datetime as dt
from pathlib import Path
import math
import pandas as pd
import numpy as np
import requests

# ================== CONFIG ==================
BASE_CURRENCY = os.getenv("BASE_CURRENCY", "USD").upper()   # "USD" or "INR"
STARTING_CASH = float(os.getenv("STARTING_CASH_USD", "10000000"))  # if BASE=INR, interpret as INR
YEARS_BACK = int(os.getenv("YEARS_BACK", "5"))
API_KEY = os.getenv("TWELVE_DATA_KEY", "").strip()
REQUESTS_PER_MIN = int(os.getenv("TD_REQ_PER_MIN", "8"))  # free tier throttle
# ============================================

if not API_KEY:
    print("ERROR: missing TWELVE_DATA_KEY env var", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
QUOTES = DATA / "quotes"
QUOTES.mkdir(parents=True, exist_ok=True)

stocks_json = DATA / "stocks.json"
tx_json = DATA / "transactions.json"  # optional

def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)

if not stocks_json.exists():
    die("data/stocks.json not found")

try:
    stocks = json.loads(stocks_json.read_text(encoding="utf-8"))
except Exception as e:
    die(f"failed to parse data/stocks.json: {e}")
if not isinstance(stocks, list) or not stocks:
    die("data/stocks.json must be a non-empty JSON array")

print(f"[info] BASE_CURRENCY={BASE_CURRENCY}")
print(f"[info] STARTING_CASH={STARTING_CASH:,.2f}")
print(f"[info] YEARS_BACK={YEARS_BACK}")

# ---------- Symbol mapping helpers (NSE/BSE) ----------
def parse_symbol(s: str):
    """
    Input examples from stocks.json:
      - 'COALINDIA.NS'  -> base='COALINDIA', exch='NSE'
      - 'KIRLOSBROS.NS' -> base='KIRLOSBROS', exch='NSE'
      - 'RELIANCE.BO'   -> base='RELIANCE',  exch='BSE'
      - 'AAPL'          -> base='AAPL',      exch=None (US)
    Twelve Data: prefer symbol+exchange params (e.g., symbol=COALINDIA&exchange=NSE)
    """
    s = (s or "").upper().strip()
    base, exch = s, None
    if s.endswith(".NS"):
        base, exch = s[:-3], "NSE"
    elif s.endswith(".BO"):
        base, exch = s[:-3], "BSE"
    return base, exch

def local_currency(sym: str) -> str:
    s = (sym or "").upper()
    if s.endswith(".NS") or s.endswith(".BO"):
        return "INR"
    return "USD"

# ---------- Twelve Data helpers ----------
BASE_URL = "https://api.twelvedata.com/time_series"

def td_fetch_timeseries(symbol_base: str, exchange: str | None, start_date: str, end_date: str) -> pd.DataFrame:
    """
    Fetch daily time series for a symbol from Twelve Data.
    Returns DataFrame with columns: date, close (float). Newest first in TD, we reverse.
    """
    params = {
        "symbol": symbol_base,
        "interval": "1day",
        "apikey": API_KEY,
        "format": "JSON",
        "outputsize": 5000,  # generous
        "start_date": start_date,
        "end_date": end_date,
        "order": "ASC"
    }
    if exchange:
        params["exchange"] = exchange

    r = requests.get(BASE_URL, params=params, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} for {symbol_base}:{exchange} -> {r.text[:200]}")

    data = r.json()
    if "values" not in data:
        # Sometimes TD returns {"status":"error","message":"..."}
        raise RuntimeError(f"No 'values' in response for {symbol_base}:{exchange} -> {str(data)[:200]}")

    rows = data["values"]
    if not rows:
        return pd.DataFrame(columns=["date", "close"])

    # rows are dicts: {"datetime":"2024-08-22","close":"123.45",...}
    df = pd.DataFrame(rows)
    # standardize
    df = df.rename(columns={"datetime": "date"})
    df["date"] = pd.to_datetime(df["date"]).dt.date.astype(str)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df[["date", "close"]].dropna().sort_values("date")
    return df

def td_fetch_fx_usdinr(start_date: str, end_date: str) -> pd.DataFrame:
    # Twelve Data uses "USD/INR" as symbol for FX
    params = {
        "symbol": "USD/INR",
        "interval": "1day",
        "apikey": API_KEY,
        "format": "JSON",
        "outputsize": 5000,
        "start_date": start_date,
        "end_date": end_date,
        "order": "ASC"
    }
    r = requests.get(BASE_URL, params=params, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"FX HTTP {r.status_code} -> {r.text[:200]}")
    data = r.json()
    if "values" not in data or not data["values"]:
        raise RuntimeError(f"FX missing 'values' -> {str(data)[:200]}")
    df = pd.DataFrame(data["values"]).rename(columns={"datetime":"date"})
    df["date"] = pd.to_datetime(df["date"]).dt.date.astype(str)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df[["date", "close"]].dropna().sort_values("date")
    return df

# ---------- Time window ----------
today = dt.date.today()
start = (today - dt.timedelta(days=YEARS_BACK*365 + 30)).isoformat()
end = today.isoformat()
print(f"[info] fetching range: {start} -> {end}")

# ---------- Fetch quotes for each stock ----------
symbols = []
meta = []
for s in stocks:
    sym = (s.get("symbol") or s.get("ticker") or "").strip()
    if not sym:
        print("[warn] skipping stock without symbol/ticker:", s)
        continue
    symbols.append(sym)
    base, exch = parse_symbol(sym)
    meta.append({
        "symbol": sym,
        "base": base,
        "exchange": exch,
        "buy_date": s.get("buy_date"),
        "qty": float(s.get("qty") or 0.0),
        "buy_price": float(s.get("buy_price") or 0.0),
        "currency": s.get("currency") or local_currency(sym)
    })
if not symbols:
    die("no usable symbols in data/stocks.json")

def throttle(i, per_min=REQUESTS_PER_MIN):
    if per_min <= 0: 
        return
    # crude throttle: sleep a bit each request to stay under rate
    time.sleep(60.0 / per_min)

price_map: dict[str, pd.DataFrame] = {}
dates_set = set()

for i, m in enumerate(meta, 1):
    base, exch = m["base"], m["exchange"]
    try:
        df = td_fetch_timeseries(base, exch, start, end)
    except Exception as e:
        print(f"[warn] TD fetch failed for {base}:{exch} -> {e}")
        df = pd.DataFrame(columns=["date","close"])
    out = QUOTES / f"{m['symbol']}.json"
    df.to_json(out, orient="records", force_ascii=False)
    price_map[m['symbol']] = df
    dates_set |= set(df["date"].unique())
    print(f"[ok] wrote data/quotes/{m['symbol']}.json rows={len(df)}")
    throttle(i)

if not dates_set:
    die("no quote data fetched for any symbol (check Twelve Data symbol/exchange mapping)")

all_dates = pd.Series(sorted(list(dates_set)), dtype="string")

# ---------- Transactions (optional) ----------
if tx_json.exists():
    try:
        tx = pd.read_json(tx_json)
        tx["date"] = pd.to_datetime(tx["date"]).dt.date.astype(str)
        tx = tx[tx["symbol"].isin(symbols)]
        print(f"[info] transactions loaded: {len(tx)} rows")
    except Exception as e:
        die(f"failed to read data/transactions.json: {e}")
else:
    tx = pd.DataFrame(columns=["date","symbol","qty","price"])

if tx.empty:
    rows = []
    for m in meta:
        if (m["qty"] or 0) > 0 and m.get("buy_date"):
            rows.append({
                "date": m["buy_date"], "symbol": m["symbol"],
                "qty": m["qty"], "price": m.get("buy_price", 0.0)
            })
    tx = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["date","symbol","qty","price"])
    print(f"[info] synthesized transactions: {len(tx)} rows")
tx = tx.sort_values("date")

# ---------- FX (USD/INR) series if needed ----------
need_fx = any((m["currency"].upper() != BASE_CURRENCY) for m in meta)
fx_series = None
if need_fx:
    try:
        fx_df = td_fetch_fx_usdinr(start, end)  # USD/INR (how many INR per 1 USD)
        fx_series = fx_df.set_index("date")["close"]
        print(f"[ok] FX USD/INR rows={len(fx_df)}")
    except Exception as e:
        print(f"[warn] FX fetch failed: {e} — will proceed without conversion (units may mix)")

def convert_to_base(series_local: pd.Series, local_cur: str) -> pd.Series:
    if local_cur.upper() == BASE_CURRENCY or fx_series is None:
        return series_local
    aligned_fx = fx_series.reindex(series_local.index).ffill()
    if BASE_CURRENCY == "USD" and local_cur.upper() == "INR":
        # price_usd = price_inr / (INR per USD)
        return series_local / aligned_fx
    if BASE_CURRENCY == "INR" and local_cur.upper() == "USD":
        # price_inr = price_usd * (INR per USD)
        return series_local * aligned_fx
    # fallback: no conversion rule
    return series_local

# ---------- Build holdings per day ----------
holdings = {m["symbol"]: pd.Series(0.0, index=all_dates) for m in meta}
invested_base = pd.Series(0.0, index=all_dates)  # cumulative invested in BASE

def tx_price_to_base(symbol: str, price_local: float, on_date: str) -> float:
    m = next(x for x in meta if x["symbol"] == symbol)
    cur = m["currency"]
    tmp = pd.Series([price_local], index=pd.Index([on_date], dtype="string"))
    conv = convert_to_base(tmp, cur)
    return float(conv.iloc[0])

for m in meta:
    sym = m["symbol"]
    h = pd.Series(0.0, index=all_dates)
    sym_tx = tx[tx["symbol"] == sym]
    for _, row in sym_tx.iterrows():
        h.loc[h.index >= row["date"]] += float(row["qty"])
        price_base = tx_price_to_base(sym, float(row.get("price", 0.0)), row["date"])
        invested_base.loc[invested_base.index >= row["date"]] += float(row["qty"]) * price_base
    holdings[sym] = h

# ---------- Daily holdings value (in BASE) ----------
values_base = pd.Series(0.0, index=all_dates, dtype=float)

for m in meta:
    sym = m["symbol"]
    qdf = price_map[sym].set_index("date")["close"].reindex(all_dates).ffill()
    price_base_series = convert_to_base(qdf, m["currency"])
    values_base += price_base_series * holdings[sym]

# ---------- Cash & NAV ----------
cash_base = (STARTING_CASH - invested_base).clip(lower=0.0)
nav_base = (values_base + cash_base).round(4)

# NAV index (100 = inception)
nonzero = nav_base[nav_base > 0]
if nonzero.empty:
    inception = None
    nav_index = pd.Series(np.nan, index=all_dates)
    pnl_abs = pd.Series(np.nan, index=all_dates)
    pnl_pct = pd.Series(np.nan, index=all_dates)
else:
    inception = nonzero.index.min()
    base_val = nav_base.loc[inception]
    nav_index = (nav_base / base_val * 100.0).round(4)
    pnl_abs = (nav_base - base_val).round(2)
    pnl_pct = ((nav_base / base_val - 1.0) * 100.0).round(3)

# ---------- Write outputs ----------
nav_df = pd.DataFrame({
    "date": all_dates,
    f"nav_{BASE_CURRENCY.lower()}": nav_base,
    f"cash_{BASE_CURRENCY.lower()}": cash_base.round(4),
    f"holdings_{BASE_CURRENCY.lower()}": values_base.round(4),
    f"invested_{BASE_CURRENCY.lower()}": invested_base.round(4),
    "nav_index": nav_index,
    f"pnl_abs_{BASE_CURRENCY.lower()}": pnl_abs,
    "pnl_pct": pnl_pct
})

out_nav = DATA / "nav.json"
nav_df.to_json(out_nav, orient="records", force_ascii=False)
print(f"[ok] wrote {out_nav.relative_to(ROOT)} rows={len(nav_df)}")

latest_idx = len(all_dates) - 1
latest = {
    "date": all_dates.iloc[latest_idx],
    "nav": float(nav_base.iloc[latest_idx]),
    "cash": float(cash_base.iloc[latest_idx]),
    "holdings": float(values_base.iloc[latest_idx]),
    "invested": float(invested_base.iloc[latest_idx]),
    "pnl_abs": float(pnl_abs.iloc[latest_idx]) if not pd.isna(pnl_abs.iloc[latest_idx]) else None,
    "pnl_pct": float(pnl_pct.iloc[latest_idx]) if not pd.isna(pnl_pct.iloc[latest_idx]) else None
}
summary = {
    "base_currency": BASE_CURRENCY,
    "starting_cash": STARTING_CASH,
    "inception_date": inception if inception else None,
    "latest": latest
}
out_sum = DATA / "nav_summary.json"
out_sum.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[ok] wrote {out_sum.relative_to(ROOT)}")

print("[done] quotes + NAV generation complete (Twelve Data)")
