import os, sys, json, time, datetime as dt
from pathlib import Path
import pandas as pd
import numpy as np
import requests

# ================== CONFIG (via env) ==================
# Set to "INR" (default) for immediate success with NSE/BSE.
# You can change to "USD" later and add USD/INR FX support.
BASE_CURRENCY = os.getenv("BASE_CURRENCY", "INR").upper()   # "INR" or "USD"
STARTING_CASH = float(os.getenv("STARTING_CASH", os.getenv("STARTING_CASH_USD", "10000000")))
YEARS_BACK = int(os.getenv("YEARS_BACK", "5"))
API_KEY = os.getenv("FINNHUB_KEY", "").strip()
REQS_PER_MIN = int(os.getenv("FH_REQS_PER_MIN", "50"))  # free tier is generous
# ======================================================

if not API_KEY:
    print("ERROR: FINNHUB_KEY is missing (set it as a repo secret).", file=sys.stderr)
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

# -------- symbol helpers (Yahoo-style -> Finnhub-style) ----------
def parse_symbol_yahoo(y):
    """
    'COALINDIA.NS' -> ('COALINDIA', 'NSE')
    'RELIANCE.BO'  -> ('RELIANCE',  'BSE')
    'AAPL'         -> ('AAPL',      None)
    Finnhub wants 'Exchange_Ticker.Exchange_Code' i.e. AAPL.US, RELIANCE.BSE, COALINDIA.NSE
    """
    y = (y or "").upper().strip()
    if y.endswith(".NS"):
        return y[:-3], "NSE"
    if y.endswith(".BO"):
        return y[:-3], "BSE"
    # assume US if bare
    return y, "US"

def to_finnhub_symbol(y):
    base, exch = parse_symbol_yahoo(y)
    # Common exchange codes Finnhub uses: US, NSE, BSE, LSE, ...
    return f"{base}.{exch}" if exch else base

def local_currency(y):
    y = (y or "").upper()
    if y.endswith(".NS") or y.endswith(".BO"):
        return "INR"
    return "USD"

# -------- Finnhub REST helpers ----------
FH_BASE = "https://finnhub.io/api/v1"

def fh_get(path, params):
    params = dict(params or {})
    params["token"] = API_KEY
    r = requests.get(f"{FH_BASE}{path}", params=params, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()

def fh_candles(symbol, resolution, t_from, t_to):
    """Return pandas DataFrame with columns date, close sorted asc.
       Finnhub returns JSON with keys s,status; c(lose), t(imes) arrays.
    """
    data = fh_get("/stock/candle", {
        "symbol": symbol, "resolution": resolution, "from": t_from, "to": t_to
    })
    if not data or data.get("s") != "ok":
        # could be s=no_data
        return pd.DataFrame(columns=["date", "close"])
    t = data.get("t", [])
    c = data.get("c", [])
    if not t or not c:
        return pd.DataFrame(columns=["date", "close"])
    dates = pd.to_datetime(pd.Series(t), unit="s").dt.date.astype(str)
    closes = pd.Series(c, dtype=float)
    df = pd.DataFrame({"date": dates, "close": closes}).dropna().sort_values("date")
    return df

def throttle(i):
    if REQS_PER_MIN <= 0: return
    # very light throttle to be nice (Finnhub free is ~60/min)
    time.sleep(60.0 / REQS_PER_MIN)

# -------- Time window in UNIX (Finnhub needs epoch seconds) ----------
today = dt.date.today()
start_date = (today - dt.timedelta(days=YEARS_BACK*365 + 30))
from_ts = int(dt.datetime.combine(start_date, dt.time.min).timestamp())
to_ts   = int(dt.datetime.combine(today, dt.time.max).timestamp())
print(f"[info] fetching candles from {start_date.isoformat()} -> {today.isoformat()}")

# -------- Collect symbols & metadata ----------
symbols = []
meta = []
for s in stocks:
    sym = (s.get("symbol") or s.get("ticker") or "").strip()
    if not sym:
        print("[warn] skipping stock without symbol/ticker:", s)
        continue
    symbols.append(sym)
    meta.append({
        "symbol": sym,
        "fh_symbol": to_finnhub_symbol(sym),
        "buy_date": s.get("buy_date"),
        "qty": float(s.get("qty") or 0.0),
        "buy_price": float(s.get("buy_price") or 0.0),
        "currency": s.get("currency") or local_currency(sym)
    })
if not symbols:
    die("no usable symbols in data/stocks.json")

# -------- Fetch candles & persist per-symbol JSON ----------
price_map = {}
dates_set = set()

for i, m in enumerate(meta, 1):
    fh_sym = m["fh_symbol"]
    try:
        df = fh_candles(fh_sym, "D", from_ts, to_ts)
    except Exception as e:
        print(f"[warn] Finnhub fetch failed for {fh_sym}: {e}")
        df = pd.DataFrame(columns=["date", "close"])
    out = QUOTES / f"{m['symbol']}.json"
    df.to_json(out, orient="records", force_ascii=False)
    price_map[m["symbol"]] = df
    dates_set |= set(df["date"].unique())
    print(f"[ok] wrote data/quotes/{m['symbol']}.json rows={len(df)}")
    throttle(i)

if not dates_set:
    die("no quote data fetched for any symbol (Finnhub blocked symbol or mapping wrong)")

all_dates = pd.Series(sorted(list(dates_set)), dtype="string")

# -------- Transactions (optional) ----------
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

# -------- Build holdings time series ----------
def align_ffill(dates: pd.Series, s: pd.Series) -> pd.Series:
    return s.reindex(dates).ffill()

holdings = {m["symbol"]: pd.Series(0.0, index=all_dates) for m in meta}
invested = pd.Series(0.0, index=all_dates)  # cumulative invested (in BASE_CURRENCY)

def tx_price_to_base(symbol: str, price_local: float, on_date: str) -> float:
    # Since BASE is INR by default and NSE is INR, we return as-is.
    # If you switch BASE to USD later, add USD/INR conversion here.
    return float(price_local)

for m in meta:
    sym = m["symbol"]
    h = pd.Series(0.0, index=all_dates)
    sym_tx = tx[tx["symbol"] == sym]
    for _, row in sym_tx.iterrows():
        h.loc[h.index >= row["date"]] += float(row["qty"])
        invested.loc[invested.index >= row["date"]] += float(row["qty"]) * tx_price_to_base(sym, float(row.get("price", 0.0)), row["date"])
    holdings[sym] = h

# -------- Value holdings (in BASE_CURRENCY) ----------
values = pd.Series(0.0, index=all_dates, dtype=float)

for m in meta:
    sym = m["symbol"]
    qdf = price_map[sym].set_index("date")["close"]
    qdf = align_ffill(all_dates, qdf)
    # If BASE=INR and symbol is INR, add directly. If BASE=USD later, convert here with FX.
    values += qdf * holdings[sym]

cash = (STARTING_CASH - invested).clip(lower=0.0)
nav = (values + cash).round(4)

# -------- NAV index, P&L ----------
nonzero = nav[nav > 0]
if nonzero.empty:
    inception = None
    nav_index = pd.Series(np.nan, index=all_dates)
    pnl_abs = pd.Series(np.nan, index=all_dates)
    pnl_pct = pd.Series(np.nan, index=all_dates)
else:
    inception = nonzero.index.min()
    base_val = nav.loc[inception]
    nav_index = (nav / base_val * 100.0).round(4)
    pnl_abs = (nav - base_val).round(2)
    pnl_pct = ((nav / base_val - 1.0) * 100.0).round(3)

# -------- Write outputs ----------
nav_df = pd.DataFrame({
    "date": all_dates,
    f"nav_{BASE_CURRENCY.lower()}": nav,
    f"cash_{BASE_CURRENCY.lower()}": cash.round(4),
    f"holdings_{BASE_CURRENCY.lower()}": values.round(4),
    f"invested_{BASE_CURRENCY.lower()}": invested.round(4),
    "nav_index": nav_index,
    f"pnl_abs_{BASE_CURRENCY.lower()}": pnl_abs,
    "pnl_pct": pnl_pct
})

out_nav = DATA / "nav.json"
nav_df.to_json(out_nav, orient="records", force_ascii=False)
print(f"[ok] wrote {out_nav.relative_to(ROOT)} rows={len(nav_df)}")

latest = {
    "date": all_dates.iloc[-1],
    "nav": float(nav.iloc[-1]),
    "cash": float(cash.iloc[-1]),
    "holdings": float(values.iloc[-1]),
    "invested": float(invested.iloc[-1]),
    "pnl_abs": float(pnl_abs.iloc[-1]) if not pd.isna(pnl_abs.iloc[-1]) else None,
    "pnl_pct": float(pnl_pct.iloc[-1]) if not pd.isna(pnl_pct.iloc[-1]) else None
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

print("[done] quotes + NAV generation complete (Finnhub)")

