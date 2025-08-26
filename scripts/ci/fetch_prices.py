#!/usr/bin/env python3
import os, sys, json, datetime as dt
from pathlib import Path
from urllib.parse import quote
from io import StringIO
import pandas as pd
import numpy as np
import requests

# ================== CONFIG ==================
BASE_CURRENCY = os.getenv("BASE_CURRENCY", "USD").upper()
STARTING_CASH = float(os.getenv("STARTING_CASH", os.getenv("STARTING_CASH_USD", "10000000")))
YEARS_BACK = int(os.getenv("YEARS_BACK", "5"))
SHEET_ID = os.getenv("SHEET_ID", "").strip()
TAB_GIDS_JSON = os.getenv("TAB_GIDS_JSON", "").strip()  # optional secret/var with symbol->gid map
# ============================================

if not SHEET_ID:
    print("ERROR: SHEET_ID env var is missing.", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
QUOTES = DATA / "quotes"
QUOTES.mkdir(parents=True, exist_ok=True)

stocks_json = DATA / "stocks.json"
tx_json = DATA / "transactions.json"
tab_gids_path = DATA / "tab_gids.json"  # optional file fallback

def die(msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)

def default_tab(symbol: str) -> str:
    # COALINDIA.NS -> COALINDIA_NS
    return (symbol or "").upper().replace(".", "_")

def load_tab_gids() -> dict:
    # Priority: env secret TAB_GIDS_JSON > data/tab_gids.json > {}
    if TAB_GIDS_JSON:
        try:
            return json.loads(TAB_GIDS_JSON)
        except Exception as e:
            print(f"[warn] TAB_GIDS_JSON parse failed: {e}")
    if tab_gids_path.exists():
        try:
            return json.loads(tab_gids_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[warn] data/tab_gids.json parse failed: {e}")
    return {}

def fetch_gid_csv(sheet_id: str, gid: str) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    print(f"[fetch-gid] {gid} -> {url}")
    r = requests.get(url, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} (gid {gid}) {r.text[:120]}")
    df = pd.read_csv(StringIO(r.text))
    if df.shape[1] < 2:
        return pd.DataFrame(columns=["date","close"])
    df = df.rename(columns={df.columns[0]:"date", df.columns[1]:"close"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date.astype("string")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna().sort_values("date")
    start_date = (dt.date.today() - dt.timedelta(days=YEARS_BACK*365 + 30)).isoformat()
    return df[df["date"] >= start_date][["date","close"]]

def fetch_tab_csv(sheet_id: str, tab: str) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={quote(tab)}"
    print(f"[fetch-tab] {tab} -> {url}")
    r = requests.get(url, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} (tab {tab}) {r.text[:120]}")
    df = pd.read_csv(StringIO(r.text))
    if df.shape[1] < 2:
        return pd.DataFrame(columns=["date","close"])
    df = df.rename(columns={df.columns[0]:"date", df.columns[1]:"close"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date.astype("string")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna().sort_values("date")
    start_date = (dt.date.today() - dt.timedelta(days=YEARS_BACK*365 + 30)).isoformat()
    return df[df["date"] >= start_date][["date","close"]]

def local_cur(symbol: str) -> str:
    s = (symbol or "").upper()
    if s.endswith(".NS") or s.endswith(".BO"):
        return "INR"
    return "USD"

def load_stocks():
    if not stocks_json.exists():
        die("data/stocks.json not found")
    try:
        stocks = json.loads(stocks_json.read_text(encoding="utf-8"))
    except Exception as e:
        die(f"failed to parse data/stocks.json: {e}")
    if not isinstance(stocks, list) or not stocks:
        die("data/stocks.json must be a non-empty JSON array")
    return stocks

def synth_tx(stocks):
    rows=[]
    for s in stocks:
        qty=float(s.get("qty") or 0)
        bd=s.get("buy_date")
        if qty>0 and bd:
            rows.append({"date":bd,"symbol":s.get("symbol") or s.get("ticker"),
                         "qty":qty,"price":float(s.get("buy_price") or 0)})
    return pd.DataFrame(rows, columns=["date","symbol","qty","price"]).sort_values("date")

def main():
    print(f"[info] BASE={BASE_CURRENCY}  STARTING_CASH={STARTING_CASH:,.2f}  YEARS_BACK={YEARS_BACK}")
    gids = load_tab_gids()
    if gids: print(f"[info] using gid mapping for {len(gids)} tabs")

    stocks = load_stocks()
    symbols = [(s.get("symbol") or s.get("ticker") or "").strip() for s in stocks if (s.get("symbol") or s.get("ticker"))]
    if not symbols:
        die("no usable symbols in data/stocks.json")

    # Fetch price series
    price_map={}; all_dates=set()
    for sym in symbols:
        df=None
        gid = gids.get(sym)
        if gid:
            try:
                df = fetch_gid_csv(SHEET_ID, gid)
            except Exception as e:
                print(f"[warn] gid fetch failed for {sym}: {e}")
        if df is None:
            tab = sym if sym=="USDINR" else default_tab(sym)
            try:
                df = fetch_tab_csv(SHEET_ID, tab)
            except Exception as e:
                print(f"[warn] tab fetch failed for {sym} (tab {tab}): {e}")
                df = pd.DataFrame(columns=["date","close"])
        (QUOTES / f"{sym}.json").write_text(df.to_json(orient="records", force_ascii=False), encoding="utf-8")
        price_map[sym]=df
        all_dates |= set(df["date"].unique())
        print(f"[ok] wrote data/quotes/{sym}.json rows={len(df)}")

    if not all_dates:
        die("no quote data fetched (sharing/publish or mapping issue)")
    all_dates = pd.Series(sorted(list(all_dates)), dtype="string")

    # FX: USDINR for INR->USD
    fx = pd.Series(dtype=float); have_fx=False
    fx_df=None
    fx_gid = gids.get("USDINR")
    if fx_gid:
        try:
            fx_df = fetch_gid_csv(SHEET_ID, fx_gid)
        except Exception as e:
            print(f"[warn] gid USDINR failed: {e}")
    if fx_df is None:
        try:
            fx_df = fetch_tab_csv(SHEET_ID, "USDINR")
        except Exception as e:
            print(f"[warn] USDINR tab fetch failed: {e}")
    if fx_df is not None and len(fx_df):
        fx = fx_df.set_index("date")["close"]
        have_fx=True
        print(f"[ok] USDINR rows={len(fx_df)}")
    else:
        print("[warn] No USDINR FX; INR values will be treated as USD (mis-scaled)")

    # Transactions
    if tx_json.exists():
        try:
            tx = pd.read_json(tx_json)
            tx["date"]=pd.to_datetime(tx["date"]).dt.date.astype("string")
            tx = tx[tx["symbol"].isin(symbols)]
            print(f"[info] transactions loaded: {len(tx)} rows")
        except Exception as e:
            die(f"failed to read data/transactions.json: {e}")
    else:
        tx = synth_tx(stocks)
        print(f"[info] synthesized transactions: {len(tx)} rows")

    # Helpers for conversion
    def series_to_usd(s: pd.Series, sym: str)->pd.Series:
        cur = local_cur(sym)
        if cur=="USD":
            return s
        if cur=="INR" and have_fx:
            return s / fx.reindex(s.index).ffill()
        return s

    def tx_to_usd(sym: str, price_local: float, on_date: str)->float:
        cur = local_cur(sym)
        if cur=="USD":
            return float(price_local)
        if cur=="INR" and have_fx:
            fxv = fx.reindex([on_date]).ffill().iloc[0]
            return float(price_local)/float(fxv)
        return float(price_local)

    # Holdings & invested (by date)
    holdings={sym: pd.Series(0.0, index=all_dates) for sym in symbols}
    invested_usd=pd.Series(0.0, index=all_dates)
    for sym in symbols:
        h=pd.Series(0.0, index=all_dates)
        for _,row in tx[tx["symbol"]==sym].iterrows():
            h.loc[h.index>=row["date"]] += float(row["qty"])
            invested_usd.loc[invested_usd.index>=row["date"]] += float(row["qty"]) * tx_to_usd(sym, float(row.get("price",0.0)), row["date"])
        holdings[sym]=h

    # Daily mark-to-market (USD) — avoid NaNs at source
    values_usd=pd.Series(0.0, index=all_dates, dtype=float)
    for sym in symbols:
        s = price_map[sym].set_index("date")["close"].reindex(all_dates).ffill().fillna(0.0)
        s_usd = series_to_usd(s, sym).fillna(0.0)
        values_usd += s_usd * holdings[sym]

    # Cash & NAV (fill any gaps)
    invested_usd = invested_usd.fillna(0.0)
    cash_usd = (STARTING_CASH - invested_usd).clip(lower=0.0)
    cash_usd = cash_usd.fillna(method='ffill').fillna(STARTING_CASH)
    nav_usd  = (values_usd + cash_usd).round(4)
    nav_usd  = nav_usd.fillna(cash_usd)

    # Inception = first date with positive invested cash, else first positive NAV
    invested_positive = invested_usd[invested_usd > 0]
    if len(invested_positive):
        inception = invested_positive.index.min()
    else:
        nonzero = nav_usd[nav_usd > 0]
        inception = nonzero.index.min() if len(nonzero) else None

    if inception is None:
        nav_index = pd.Series(np.nan, index=all_dates)
        pnl_abs = pd.Series(np.nan, index=all_dates)
        pnl_pct = pd.Series(np.nan, index=all_dates)
    else:
        base_val = nav_usd.loc[inception]
        nav_index = (nav_usd / base_val * 100.0).round(4)
        pnl_abs = (nav_usd - base_val).round(2)
        pnl_pct = ((nav_usd / base_val - 1.0) * 100.0).round(3)

    # Write outputs
    nav_df=pd.DataFrame({
        "date":all_dates,
        "nav_usd":nav_usd,
        "cash_usd":cash_usd.round(4),
        "holdings_usd":values_usd.round(4),
        "invested_usd":invested_usd.round(4),
        "nav_index":nav_index,
        "pnl_abs_usd":pnl_abs,
        "pnl_pct":pnl_pct
    })
    (DATA/"nav.json").write_text(nav_df.to_json(orient="records", force_ascii=False), encoding="utf-8")

    summary={"base_currency":"USD","starting_cash":STARTING_CASH,
             "inception_date": inception if inception else None,
             "latest":{
                 "date": all_dates.iloc[-1],
                 "nav": float(nav_usd.iloc[-1]),
                 "cash": float(cash_usd.iloc[-1]),
                 "holdings": float(values_usd.iloc[-1]),
                 "invested": float(invested_usd.iloc[-1]),
                 "pnl_abs": float(pnl_abs.iloc[-1]) if not pd.isna(pnl_abs.iloc[-1]) else None,
                 "pnl_pct": float(pnl_pct.iloc[-1]) if not pd.isna(pnl_pct.iloc[-1]) else None
             }}
    (DATA/"nav_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[done] quotes + NAV generation complete")

if __name__=="__main__":
    main()
