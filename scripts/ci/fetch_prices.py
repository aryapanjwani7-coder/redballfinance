import os, sys, json, datetime as dt
from pathlib import Path
from urllib.parse import quote
import pandas as pd
import numpy as np
import requests

# ================== CONFIG ==================
BASE_CURRENCY = os.getenv("BASE_CURRENCY", "USD").upper()  # We'll run with USD
STARTING_CASH = float(os.getenv("STARTING_CASH", os.getenv("STARTING_CASH_USD", "10000000")))
YEARS_BACK = int(os.getenv("YEARS_BACK", "5"))
SHEET_ID = os.getenv("SHEET_ID", "").strip()
# ============================================

if not SHEET_ID:
    print("ERROR: SHEET_ID env var is missing. Set it as a repo secret.", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
QUOTES = DATA / "quotes"
QUOTES.mkdir(parents=True, exist_ok=True)

stocks_json = DATA / "stocks.json"
tx_json = DATA / "transactions.json"  # optional

def die(msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)

def tab_name_for_symbol(symbol: str) -> str:
    # COALINDIA.NS -> COALINDIA_NS
    return (symbol or "").upper().replace(".", "_")

def fetch_sheet_csv(sheet_id: str, sheet_tab: str) -> pd.DataFrame:
    # Export a single tab as CSV
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={quote(sheet_tab)}"
    r = requests.get(url, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} for tab {sheet_tab}")
    # Parse CSV -> expect Date, Close
    try:
        df = pd.read_csv(pd.compat.StringIO(r.text))
    except Exception:
        # pandas 2.2 deprecated compat.StringIO; fallback:
        from io import StringIO
        df = pd.read_csv(StringIO(r.text))
    if df.shape[1] < 2:
        return pd.DataFrame(columns=["date","close"])
    df = df.rename(columns={df.columns[0]:"date", df.columns[1]:"close"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date.astype("string")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna().sort_values("date")
    # clip window
    start_date = (dt.date.today() - dt.timedelta(days=YEARS_BACK*365+30)).isoformat()
    df = df[df["date"] >= start_date]
    return df[["date","close"]]

def local_currency(symbol: str) -> str:
    s = (symbol or "").upper()
    if s.endswith(".NS") or s.endswith(".BO"):
        return "INR"
    return "USD"

def load_stocks() -> list:
    if not stocks_json.exists():
        die("data/stocks.json not found")
    try:
        stocks = json.loads(stocks_json.read_text(encoding="utf-8"))
    except Exception as e:
        die(f"failed to parse data/stocks.json: {e}")
    if not isinstance(stocks, list) or not stocks:
        die("data/stocks.json must be a non-empty JSON array")
    return stocks

def synthesize_transactions(stocks: list) -> pd.DataFrame:
    rows = []
    for s in stocks:
        qty = float(s.get("qty") or 0)
        bd  = s.get("buy_date")
        if qty > 0 and bd:
            rows.append({
                "date": bd,
                "symbol": s.get("symbol") or s.get("ticker"),
                "qty": qty,
                "price": float(s.get("buy_price") or 0)
            })
    return pd.DataFrame(rows, columns=["date","symbol","qty","price"]).sort_values("date")

def align_ffill(index: pd.Series, s: pd.Series) -> pd.Series:
    return s.reindex(index).ffill()

def main():
    print(f"[info] BASE_CURRENCY={BASE_CURRENCY}")
    print(f"[info] STARTING_CASH={STARTING_CASH:,.2f}")
    print(f"[info] YEARS_BACK={YEARS_BACK}")

    if BASE_CURRENCY != "USD":
        print("[warn] This script is intended for USD base; running with", BASE_CURRENCY)

    stocks = load_stocks()
    symbols = []
    for s in stocks:
        sym = (s.get("symbol") or s.get("ticker") or "").strip()
        if sym:
            symbols.append(sym)
        else:
            print("[warn] skipping stock without symbol/ticker:", s)
    if not symbols:
        die("no usable symbols in data/stocks.json")

    # --- Fetch quotes for each stock from its tab ---
    price_map = {}
    all_dates = set()
    for sym in symbols:
        tab = tab_name_for_symbol(sym)
        try:
            df = fetch_sheet_csv(SHEET_ID, tab)
        except Exception as e:
            print(f"[warn] fetch failed for tab {tab}: {e}")
            df = pd.DataFrame(columns=["date","close"])
        out = QUOTES / f"{sym}.json"
        df.to_json(out, orient="records", force_ascii=False)
        price_map[sym] = df
        all_dates |= set(df["date"].unique())
        print(f"[ok] wrote data/quotes/{sym}.json rows={len(df)}")

    if not all_dates:
        die("no quote data fetched from Google Sheet (check publish-to-web, tab names, and formulas)")

    # --- Fetch USDINR FX from USDINR tab (needed for INR->USD) ---
    try:
        fx_df = fetch_sheet_csv(SHEET_ID, "USDINR")  # Date, Close where close = INR per 1 USD
        fx = fx_df.set_index("date")["close"]
        have_fx = len(fx_df) > 0
        print(f"[ok] USDINR rows={len(fx_df)}")
    except Exception as e:
        have_fx = False
        fx = pd.Series(dtype=float)
        print(f"[warn] USDINR tab not available or empty: {e}")

    all_dates = pd.Series(sorted(list(all_dates)), dtype="string")

    # --- Transactions (optional) ---
    if tx_json.exists():
        try:
            tx = pd.read_json(tx_json)
            tx["date"] = pd.to_datetime(tx["date"]).dt.date.astype("string")
            tx = tx[tx["symbol"].isin(symbols)]
            print(f"[info] transactions loaded: {len(tx)} rows")
        except Exception as e:
            die(f"failed to read data/transactions.json: {e}")
    else:
        tx = synthesize_transactions(stocks)
        print(f"[info] synthesized transactions: {len(tx)} rows")

    # --- Helpers for conversion ---
    def price_series_to_usd(series_local: pd.Series, sym: str) -> pd.Series:
        cur = local_currency(sym)
        if cur == "USD":
            return series_local
        if cur == "INR":
            if not have_fx:
                print(f"[warn] No USDINR FX; leaving {sym} in INR (will mis-scale USD NAV).")
                return series_local
            fx_aligned = fx.reindex(series_local.index).ffill()
            # USDINR = INR per USD → price_usd = price_inr / USDINR
            return series_local / fx_aligned
        return series_local  # extend if you add other markets

    def tx_price_to_usd(symbol: str, price_local: float, on_date: str) -> float:
        cur = local_currency(symbol)
        if cur == "USD":
            return float(price_local)
        if cur == "INR":
            if not have_fx:
                return float(price_local)
            fx_val = fx.reindex([on_date]).ffill().iloc[0]
            return float(price_local) / float(fx_val)
        return float(price_local)

    # --- Holdings time series ---
    holdings = {sym: pd.Series(0.0, index=all_dates) for sym in symbols}
    invested_usd = pd.Series(0.0, index=all_dates)  # cumulative invested in USD
    for sym in symbols:
        h = pd.Series(0.0, index=all_dates)
        sym_tx = tx[tx["symbol"] == sym]
        for _, row in sym_tx.iterrows():
            h.loc[h.index >= row["date"]] += float(row["qty"])
            invested_usd.loc[invested_usd.index >= row["date"]] += float(row["qty"]) * tx_price_to_usd(sym, float(row.get("price", 0.0)), row["date"])
        holdings[sym] = h

    # --- Daily value in USD ---
    values_usd = pd.Series(0.0, index=all_dates, dtype=float)
    for sym in symbols:
        s = price_map[sym].set_index("date")["close"].reindex(all_dates).ffill()
        s_usd = price_series_to_usd(s, sym)
        values_usd += s_usd * holdings[sym]

    # --- Cash (USD) & NAV (USD) ---
    cash_usd = (STARTING_CASH - invested_usd).clip(lower=0.0)
    nav_usd  = (values_usd + cash_usd).round(4)

    # --- NAV index & P/L ---
    nonzero = nav_usd[nav_usd > 0]
    if nonzero.empty:
        inception = None
        nav_index = pd.Series(np.nan, index=all_dates)
        pnl_abs = pd.Series(np.nan, index=all_dates)
        pnl_pct = pd.Series(np.nan, index=all_dates)
    else:
        inception = nonzero.index.min()
        base_val = nav_usd.loc[inception]
        nav_index = (nav_usd / base_val * 100.0).round(4)
        pnl_abs = (nav_usd - base_val).round(2)
        pnl_pct = ((nav_usd / base_val - 1.0) * 100.0).round(3)

    # --- Write outputs ---
    nav_df = pd.DataFrame({
        "date": all_dates,
        "nav_usd": nav_usd,
        "cash_usd": cash_usd.round(4),
        "holdings_usd": values_usd.round(4),
        "invested_usd": invested_usd.round(4),
        "nav_index": nav_index,
        "pnl_abs_usd": pnl_abs,
        "pnl_pct": pnl_pct
    })

    out_nav = DATA / "nav.json"
    nav_df.to_json(out_nav, orient="records", force_ascii=False)
    print(f"[ok] wrote {out_nav.relative_to(ROOT)} rows={len(nav_df)}")

    latest = {
        "date": all_dates.iloc[-1],
        "nav": float(nav_usd.iloc[-1]),
        "cash": float(cash_usd.iloc[-1]),
        "holdings": float(values_usd.iloc[-1]),
        "invested": float(invested_usd.iloc[-1]),
        "pnl_abs": float(pnl_abs.iloc[-1]) if not pd.isna(pnl_abs.iloc[-1]) else None,
        "pnl_pct": float(pnl_pct.iloc[-1]) if not pd.isna(pnl_pct.iloc[-1]) else None
    }
    summary = {
        "base_currency": "USD",
        "starting_cash": STARTING_CASH,
        "inception_date": inception if inception else None,
        "latest": latest
    }

    out_sum = DATA / "nav_summary.json"
    out_sum.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] wrote {out_sum.relative_to(ROOT)}")
    print("[done] quotes + NAV generation complete (Google Sheets → USD)")
if __name__ == "__main__":
    main()
