import json, os, sys, datetime as dt
from pathlib import Path
import pandas as pd
import numpy as np
import yfinance as yf

# ------------------ CONFIG ------------------
BASE_CURRENCY = "USD"
STARTING_CASH_USD = float(os.getenv("STARTING_CASH_USD", "10000000"))  # $10M default
YEARS_BACK = 5  # fetch 5y of history
# --------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
QUOTES = DATA / "quotes"
QUOTES.mkdir(parents=True, exist_ok=True)

stocks_json = DATA / "stocks.json"
tx_json = DATA / "transactions.json"  # optional

if not stocks_json.exists():
    print("ERROR: data/stocks.json not found.", file=sys.stderr); sys.exit(1)

with open(stocks_json, "r", encoding="utf-8") as f:
    stocks = json.load(f)
if not isinstance(stocks, list) or not stocks:
    print("ERROR: data/stocks.json empty/invalid.", file=sys.stderr); sys.exit(1)

# ---- helpers
def sym_to_currency(sym: str) -> str:
    """Infer trading currency. For NSE/BSE assume INR, else USD by default."""
    s = (sym or "").upper()
    if s.endswith(".NS") or s.endswith(".BO"):
        return "INR"
    return "USD"  # extend if you add other exchanges

def fx_series_needed(c: str) -> str | None:
    """Return Yahoo FX symbol to convert c -> USD (BASE_CURRENCY)."""
    if BASE_CURRENCY == "USD":
        if c == "INR": return "USDINR=X"  # USD/INR (how many INR per 1 USD)
        if c == "USD": return None
    # You can extend for other bases if needed
    return None

def to_usd(price: float, c: str, fx: float | None) -> float:
    """Convert local price to USD using the fx quote."""
    if BASE_CURRENCY == "USD":
        if c == "USD" or fx is None:
            return float(price)
        # price is in INR (local). USDINR=X is INR per 1 USD.
        #  price_local (INR) -> price_usd = price_local / (INR per USD)
        return float(price) / float(fx)
    return float(price)

# ---- Fetch quotes for each symbol (daily, adj close preferred)
today = dt.date.today()
start = (today - dt.timedelta(days=YEARS_BACK*365 + 30)).isoformat()
end = today.isoformat()

symbols = []
meta = []
for s in stocks:
    sym = (s.get("symbol") or s.get("ticker") or "").strip()
    if not sym:
        continue
    symbols.append(sym)
    meta.append({
        "symbol": sym,
        "buy_date": s.get("buy_date"),
        "qty": float(s.get("qty") or 0.0),
        "buy_price": float(s.get("buy_price") or 0.0),
        "currency": s.get("currency") or sym_to_currency(sym)
    })

def fetch_hist(sym: str) -> pd.DataFrame:
    t = yf.Ticker(sym)
    hist = t.history(interval="1d", start=start, end=end, auto_adjust=False)
    if hist.empty:
        return pd.DataFrame(columns=["date","close"])
    close = hist["Adj Close"] if "Adj Close" in hist.columns and not hist["Adj Close"].isna().all() else hist["Close"]
    df = pd.DataFrame({"date": close.index.tz_localize(None).date.astype(str), "close": close.round(6)})
    return df

# quotes per symbol
price_map = {}
dates = set()
for sym in symbols:
    df = fetch_hist(sym)
    out = QUOTES / f"{sym}.json"
    df.to_json(out, orient="records", force_ascii=False)
    price_map[sym] = df
    dates |= set(df["date"].unique())
    print(f"wrote data/quotes/{sym}.json ({len(df)} rows)")

if not dates:
    print("No quotes fetched; aborting NAV.", file=sys.stderr); sys.exit(1)

all_dates = pd.Series(sorted(list(dates)), dtype="string")

# ---- Build holdings by date
# Option A: transactions.json (recommended when you start doing adds/sells)
if tx_json.exists():
    tx = pd.read_json(tx_json)
    # normalize
    tx["date"] = pd.to_datetime(tx["date"]).dt.date.astype(str)
    tx = tx[tx["symbol"].isin(symbols)]
else:
    tx = pd.DataFrame(columns=["date","symbol","qty","price"])

# If no tx file, synthesize one lot for each stock from stocks.json
if tx.empty:
    rows = []
    for m in meta:
        if (m["qty"] or 0) > 0 and m.get("buy_date"):
            rows.append({
                "date": m["buy_date"], "symbol": m["symbol"], "qty": m["qty"], "price": m.get("buy_price", 0.0)
            })
    tx = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["date","symbol","qty","price"])

# Cumulative holdings per symbol by date
holdings = {sym: pd.Series(0.0, index=all_dates) for sym in symbols}
cost_basis_usd = pd.Series(0.0, index=all_dates)  # running invested USD (sum of qty * buy_price_usd at the time of tx)

# Preload FX series we need (to USD)
fx_needed = sorted(set(filter(None, (fx_series_needed(sym_to_currency(s)) for s in symbols))))
fx_map = {}
for fx_sym in fx_needed:
    fx_df = fetch_hist(fx_sym)
    fx_map[fx_sym] = fx_df.set_index("date")["close"]

# helper to convert a tx price to USD on that date (approx using daily close FX)
def tx_price_to_usd(symbol: str, price_local: float, on_date: str) -> float:
    cur = sym_to_currency(symbol)
    fx_sym = fx_series_needed(cur)
    if fx_sym is None:
        return float(price_local)
    # We need USDINR on that date
    s = fx_map[fx_sym].reindex(all_dates).ffill()
    fx = s.loc[on_date]
    return to_usd(price_local, cur, fx)

# Build holdings and cost basis (invested cash) over time
tx = tx.sort_values("date")
for sym in symbols:
    h = pd.Series(0.0, index=all_dates)
    for _, row in tx[tx["symbol"] == sym].iterrows():
        h.loc[h.index >= row["date"]] += float(row["qty"])
        # add invested USD from that date onward (qty * buy_price_usd)
        buy_price_usd = tx_price_to_usd(sym, float(row.get("price", 0.0)), row["date"])
        cost_basis_usd.loc[cost_basis_usd.index >= row["date"]] += float(row["qty"]) * buy_price_usd
    holdings[sym] = h

# Daily holdings value in USD
values_usd = pd.Series(0.0, index=all_dates, dtype=float)

for sym in symbols:
    qdf = price_map[sym].set_index("date")["close"].reindex(all_dates).ffill()
    # convert daily close to USD
    cur = sym_to_currency(sym)
    fx_sym = fx_series_needed(cur)
    if fx_sym:
        fx_series = fx_map[fx_sym].reindex(all_dates).ffill()
        price_usd = qdf / fx_series  # INR -> USD
    else:
        price_usd = qdf  # already USD
    values_usd += price_usd * holdings[sym]

# Cash in USD = starting cash - invested cash (cannot go below zero)
cash_usd = (STARTING_CASH_USD - cost_basis_usd).clip(lower=0.0)

# Total NAV in USD
nav_usd = (values_usd + cash_usd).round(4)

# NAV index (100 at first non-zero NAV)
first_idx = nav_usd[nav_usd > 0].index.min()
if pd.isna(first_idx):
    nav_index = pd.Series(np.nan, index=all_dates)
    inception_date = None
else:
    base = nav_usd.loc[first_idx]
    nav_index = (nav_usd / base * 100.0).round(4)
    inception_date = first_idx

# Daily P&L vs base
pnl_abs = (nav_usd - (nav_usd.loc[first_idx] if inception_date else 0)).round(2)
pnl_pct = np.where(nav_usd.loc[first_idx] > 0, (nav_usd / nav_usd.loc[first_idx] - 1.0) * 100.0, np.nan)
pnl_pct = pd.Series(pnl_pct, index=all_dates).round(3)

# Write nav.json (daily series)
out_nav = DATA / "nav.json"
pd.DataFrame({
    "date": all_dates,
    "nav_usd": nav_usd,
    "cash_usd": cash_usd.round(4),
    "holdings_usd": values_usd.round(4),
    "invested_usd": cost_basis_usd.round(4),
    "nav_index": nav_index,
    "pnl_abs_usd": pnl_abs,
    "pnl_pct": pnl_pct
}).to_json(out_nav, orient="records", force_ascii=False)
print(f"wrote data/nav.json ({len(all_dates)} rows)")

# Write a nav_summary.json for quick homepage stats
out_sum = DATA / "nav_summary.json"
summary = {
    "base_currency": BASE_CURRENCY,
    "starting_cash_usd": STARTING_CASH_USD,
    "inception_date": inception_date if inception_date else None,
    "latest": {
        "date": all_dates.iloc[-1],
        "nav_usd": float(nav_usd.iloc[-1]),
        "cash_usd": float(cash_usd.iloc[-1]),
        "holdings_usd": float(values_usd.iloc[-1]),
        "invested_usd": float(cost_basis_usd.iloc[-1]),
        "pnl_abs_usd": float(pnl_abs.iloc[-1]),
        "pnl_pct": float(pnl_pct.iloc[-1]) if not np.isnan(pnl_pct.iloc[-1]) else None
    }
}
with open(out_sum, "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print("wrote data/nav_summary.json")
