import os, sys, json, datetime as dt
from pathlib import Path
import pandas as pd
import numpy as np
import yfinance as yf

# =============== CONFIG (via env, with safe defaults) ==================
# Base currency for NAV & reporting. Use "USD" or "INR" for now.
BASE_CURRENCY = os.getenv("BASE_CURRENCY", "USD").upper()  # "USD" (default) or "INR"
# Paper portfolio starting cash (in USD terms; if BASE_CURRENCY="INR", it's INR)
STARTING_CASH = float(os.getenv("STARTING_CASH_USD", "10000000"))
# How much quote history to fetch
YEARS_BACK = int(os.getenv("YEARS_BACK", "5"))
# =======================================================================

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

# ------------------------ Helpers --------------------------------------
def sym_to_currency(sym: str) -> str:
    s = (sym or "").upper()
    if s.endswith(".NS") or s.endswith(".BO"):
        return "INR"
    return "USD"  # extend for other markets if needed

def fx_candidates(local: str, base: str) -> list[str]:
    """Return a list of Yahoo symbols to convert LOCAL -> BASE (close-enough daily)."""
    local = local.upper(); base = base.upper()
    if base == "USD" and local == "INR":
        # Either can be empty sometimes; try both
        # INR=X is USD/INR; USDINR=X is also USD/INR on Yahoo — one usually works.
        return ["INR=X", "USDINR=X"]
    if base == "INR" and local == "USD":
        # For USD -> INR we still want USD/INR; conversion formula adjusts below.
        return ["INR=X", "USDINR=X"]
    # Add more currency pairs if you add other exchanges
    return []

def fetch_hist(sym: str, start: str, end: str) -> pd.DataFrame:
    try:
        t = yf.Ticker(sym)
        hist = t.history(interval="1d", start=start, end=end, auto_adjust=False)
    except Exception as e:
        print(f"[warn] exception fetching {sym}: {e}")
        hist = pd.DataFrame()
    if hist is None or hist.empty:
        print(f"[warn] empty history for {sym}")
        return pd.DataFrame(columns=["date","close"])
    close = hist["Adj Close"] if "Adj Close" in hist.columns and not hist["Adj Close"].isna().all() else hist["Close"]
    df = pd.DataFrame({
        "date": close.index.tz_localize(None).date.astype(str),
        "close": close.round(6)
    })
    return df

def ensure_series_index(dates: pd.Series, s: pd.Series) -> pd.Series:
    """Align s to dates and forward-fill."""
    return s.reindex(dates).ffill()

# ------------------------ Time Window ----------------------------------
today = dt.date.today()
start = (today - dt.timedelta(days=YEARS_BACK*365 + 30)).isoformat()
end = today.isoformat()
print(f"[info] fetching history range: {start} -> {end}")

# ------------------------ Symbols & meta --------------------------------
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
        "buy_date": s.get("buy_date"),
        "qty": float(s.get("qty") or 0.0),
        "buy_price": float(s.get("buy_price") or 0.0),
        "currency": s.get("currency") or sym_to_currency(sym)
    })
if not symbols:
    die("no usable symbols found in data/stocks.json")

# ------------------------ Fetch quotes per symbol -----------------------
price_map: dict[str, pd.DataFrame] = {}
all_dates_set = set()
for sym in symbols:
    df = fetch_hist(sym, start, end)
    out = QUOTES / f"{sym}.json"
    df.to_json(out, orient="records", force_ascii=False)
    price_map[sym] = df
    all_dates_set |= set(df["date"].unique())
    print(f"[ok] wrote data/quotes/{sym}.json rows={len(df)}")

if not all_dates_set:
    die("no quote data fetched for any symbol (check your symbols)")

all_dates = pd.Series(sorted(list(all_dates_set)), dtype="string")

# ------------------------ Load transactions (optional) ------------------
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

# If no transactions file, synthesize one lot per stock from stocks.json
if tx.empty:
    rows = []
    for m in meta:
        if (m["qty"] or 0) > 0 and m.get("buy_date"):
            rows.append({
                "date": m["buy_date"],
                "symbol": m["symbol"],
                "qty": m["qty"],
                "price": m.get("buy_price", 0.0)
            })
    tx = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["date","symbol","qty","price"])
    print(f"[info] synthesized transactions: {len(tx)} rows")

tx = tx.sort_values("date")

# ------------------------ Preload FX series ------------------------------
# We’ll prefetch any FX series we might need (LOCAL -> BASE)
fx_needed = set()
for m in meta:
    local_cur = m["currency"].upper()
    if local_cur != BASE_CURRENCY:
        fx_needed.update(fx_candidates(local_cur, BASE_CURRENCY))

fx_map: dict[str, pd.Series] = {}
for fx in sorted(fx_needed):
    dfx = fetch_hist(fx, start, end)
    if not dfx.empty:
        fx_map[fx] = dfx.set_index("date")["close"]
        print(f"[ok] FX series {fx}: rows={len(dfx)}")
    else:
        print(f"[warn] FX series empty: {fx}")

def convert_to_base(series_local: pd.Series, local_cur: str) -> pd.Series:
    """Convert local price series to BASE_CURRENCY using available FX candidates.
       For USD base with INR local: price_usd = price_inr / (USDINR)
       For INR base with USD local: price_inr = price_usd * (USDINR)
       We use the same USDINR series and invert/multiply appropriately.
    """
    local_cur = local_cur.upper()
    if local_cur == BASE_CURRENCY:
        return series_local

    cands = fx_candidates(local_cur, BASE_CURRENCY)
    if not cands:
        print(f"[warn] no FX mapping for {local_cur}->{BASE_CURRENCY}, returning local prices")
        return series_local

    # Use the first available FX series
    for fx in cands:
        s = fx_map.get(fx)
        if s is not None and not s.empty:
            s_aligned = ensure_series_index(series_local.index, s)
            if BASE_CURRENCY == "USD" and local_cur == "INR":
                # USDINR = INR per 1 USD  -> price_usd = price_inr / USDINR
                return series_local / s_aligned
            if BASE_CURRENCY == "INR" and local_cur == "USD":
                # price_inr = price_usd * USDINR
                return series_local * s_aligned
            # Extend for other currency pairs if you add them
    print(f"[warn] no usable FX time series for {local_cur}->{BASE_CURRENCY}, returning local prices")
    return series_local

# ------------------------ Build holdings per day -------------------------
holdings = {sym: pd.Series(0.0, index=all_dates) for sym in symbols}
invested_base = pd.Series(0.0, index=all_dates)  # cumulative invested (in BASE_CURRENCY)

# For invested cash, we need to convert each tx price into BASE on that date.
def tx_price_to_base(symbol: str, price_local: float, on_date: str) -> float:
    cur = sym_to_currency(symbol)
    # Build a length-1 series to reuse convert_to_base logic with alignment
    tmp = pd.Series([price_local], index=pd.Index([on_date], dtype="string"))
    conv = convert_to_base(tmp, cur)
    return float(conv.iloc[0])

for sym in symbols:
    h = pd.Series(0.0, index=all_dates)
    sym_tx = tx[tx["symbol"] == sym]
    for _, row in sym_tx.iterrows():
        h.loc[h.index >= row["date"]] += float(row["qty"])
        price_local = float(row.get("price", 0.0))
        price_base = tx_price_to_base(sym, price_local, row["date"])
        invested_base.loc[invested_base.index >= row["date"]] += float(row["qty"]) * price_base
    holdings[sym] = h

# ------------------------ Daily holdings value (in BASE) -----------------
values_base = pd.Series(0.0, index=all_dates, dtype=float)

for sym in symbols:
    qdf = price_map[sym].set_index("date")["close"]
    qdf = ensure_series_index(all_dates, qdf)
    local_cur = sym_to_currency(sym)
    price_base_series = convert_to_base(qdf, local_cur)
    values_base += price_base_series * holdings[sym]

# ------------------------ Cash & NAV ------------------------------------
# Cash is the starting cash minus invested cash (floored at zero)
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

# ------------------------ Write outputs ---------------------------------
# nav.json: full daily series
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

# nav_summary.json: headline stats
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

print("[done] quotes + NAV generation complete")
