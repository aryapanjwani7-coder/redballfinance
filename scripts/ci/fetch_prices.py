import os, sys, json, datetime as dt
from pathlib import Path
from urllib.parse import quote
import pandas as pd
import numpy as np
import requests

# ================== CONFIG ==================
BASE_CURRENCY = os.getenv("BASE_CURRENCY", "INR").upper()  # keep INR (no FX). Switch to USD later if you add USDINR tab.
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
    # Google Sheets CSV export endpoint for a given tab
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={quote(sheet_tab)}"
    r = requests.get(url, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} for tab {sheet_tab}")
    # Expected CSV columns: Date, Close (from GOOGLEFINANCE)
    df = pd.read_csv(pd.compat.StringIO(r.text))
    # Some locales label columns differently; normalize by position
    if df.shape[1] < 2:
        return pd.DataFrame(columns=["date","close"])
    df = df.rename(columns={df.columns[0]:"date", df.columns[1]:"close"})
    # clean
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date.astype("string")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna().sort_values("date")
    # clip to YEARS_BACK
    start_date = (dt.date.today() - dt.timedelta(days=YEARS_BACK*365+30)).isoformat()
    df = df[df["date"] >= start_date]
    return df[["date","close"]]

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

    # --- Fetch quotes from Google Sheet tabs ---
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

    # --- Holdings timeseries ---
    holdings = {sym: pd.Series(0.0, index=all_dates) for sym in symbols}
    invested = pd.Series(0.0, index=all_dates)  # in BASE_CURRENCY (INR here)

    for sym in symbols:
        h = pd.Series(0.0, index=all_dates)
        sym_tx = tx[tx["symbol"] == sym]
        for _, row in sym_tx.iterrows():
            h.loc[h.index >= row["date"]] += float(row["qty"])
            invested.loc[invested.index >= row["date"]] += float(row["qty"]) * float(row.get("price", 0.0))
        holdings[sym] = h

    # --- Daily value (BASE_CURRENCY) ---
    values = pd.Series(0.0, index=all_dates, dtype=float)

    for sym in symbols:
        df = price_map[sym].set_index("date")["close"]
        df = align_ffill(all_dates, df)
        values += df * holdings[sym]

    cash = (STARTING_CASH - invested).clip(lower=0.0)
    nav  = (values + cash).round(4)

    # --- NAV index, P&L ---
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

    # --- Write outputs ---
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
    print("[done] quotes + NAV generation complete (Google Sheets source)")

if __name__ == "__main__":
    main()
