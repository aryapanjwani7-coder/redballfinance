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
TAB_GIDS_JSON = os.getenv("TAB_GIDS_JSON", "").strip()  # optional JSON mapping: {"COALINDIA.NS":"0", ...}
# ============================================

if not SHEET_ID:
    print("ERROR: SHEET_ID env var is missing.", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[2]   # <repo root>
DATA = ROOT / "data"
QUOTES = DATA / "quotes"
QUOTES.mkdir(parents=True, exist_ok=True)

tx_json = DATA / "transactions.json"      # required
tab_gids_path = DATA / "tab_gids.json"    # optional local fallback

def die(msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr); sys.exit(code)

def default_tab(symbol: str) -> str:
    # COALINDIA.NS -> COALINDIA_NS (matches your Sheet tab name style)
    return (symbol or "").upper().replace(".", "_")

def load_tab_gids() -> dict:
    if TAB_GIDS_JSON:
        try: return json.loads(TAB_GIDS_JSON)
        except Exception as e: print(f"[warn] TAB_GIDS_JSON parse failed: {e}")
    if tab_gids_path.exists():
        try: return json.loads(tab_gids_path.read_text(encoding="utf-8"))
        except Exception as e: print(f"[warn] data/tab_gids.json parse failed: {e}")
    return {}

def fetch_gid_csv(sheet_id: str, gid: str) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    print(f"[fetch-gid] {gid} -> {url}")
    r = requests.get(url, timeout=60)
    if r.status_code != 200: raise RuntimeError(f"HTTP {r.status_code} (gid {gid}) {r.text[:120]}")
    df = pd.read_csv(StringIO(r.text))
    if df.shape[1] < 2: return pd.DataFrame(columns=["date","close"])
    df = df.rename(columns={df.columns[0]:"date", df.columns[1]:"close"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date.astype("string")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna().sort_values("date")
    start = (dt.date.today() - dt.timedelta(days=YEARS_BACK*365 + 30)).isoformat()
    return df[df["date"] >= start][["date","close"]]

def fetch_tab_csv(sheet_id: str, tab: str) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={quote(tab)}"
    print(f"[fetch-tab] {tab} -> {url}")
    r = requests.get(url, timeout=60)
    if r.status_code != 200: raise RuntimeError(f"HTTP {r.status_code} (tab {tab}) {r.text[:120]}")
    df = pd.read_csv(StringIO(r.text))
    if df.shape[1] < 2: return pd.DataFrame(columns=["date","close"])
    df = df.rename(columns={df.columns[0]:"date", df.columns[1]:"close"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date.astype("string")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna().sort_values("date")
    start = (dt.date.today() - dt.timedelta(days=YEARS_BACK*365 + 30)).isoformat()
    return df[df["date"] >= start][["date","close"]]

def local_cur(symbol: str) -> str:
    s = (symbol or "").upper()
    if s.endswith(".NS") or s.endswith(".BO"): return "INR"
    return "USD"

def load_transactions() -> pd.DataFrame:
    if not tx_json.exists(): die("data/transactions.json not found — create it with your buys.")
    try: tx = pd.read_json(tx_json)
    except Exception as e: die(f"failed to parse data/transactions.json: {e}")
    for col in ["symbol","date","price_local"]:
        if col not in tx.columns: die(f"transactions.json missing required field '{col}'")
    tx["symbol"] = tx["symbol"].astype(str)
    tx["date"]   = pd.to_datetime(tx["date"]).dt.date.astype("string")
    for col in ["qty","price_local","amount_usd"]:
        if col in tx.columns: tx[col] = pd.to_numeric(tx[col], errors="coerce")
    return tx.sort_values("date")

def main():
    print(f"[info] BASE={BASE_CURRENCY}  STARTING_CASH={STARTING_CASH:,.2f}  YEARS_BACK={YEARS_BACK}")
    gids = load_tab_gids()
    if gids: print(f"[info] using gid mapping for {len(gids)} tabs")

    tx = load_transactions()
    symbols = sorted(tx["symbol"].unique())

    # --- Fetch quotes for each symbol ---
    price_map, all_dates = {}, set()
    def fetch_prices(sym: str) -> pd.DataFrame:
        df=None
        gid = gids.get(sym)
        if gid:
            try: df = fetch_gid_csv(SHEET_ID, gid)
            except Exception as e: print(f"[warn] gid fetch failed for {sym}: {e}")
        if df is None:
            tab = sym if sym=="USDINR" else default_tab(sym)
            try: df = fetch_tab_csv(SHEET_ID, tab)
            except Exception as e:
                print(f"[warn] tab fetch failed for {sym} (tab {tab}): {e}")
                df = pd.DataFrame(columns=["date","close"])
        (QUOTES / f"{sym}.json").write_text(df.to_json(orient="records", force_ascii=False), encoding="utf-8")
        print(f"[ok] wrote data/quotes/{sym}.json rows={len(df)}")
        return df

    for sym in symbols:
        df = fetch_prices(sym)
        price_map[sym] = df
        all_dates |= set(df["date"].unique())

    # --- FX: USDINR (for INR -> USD) ---
    fx_df=None
    if "USDINR" in gids:
        try: fx_df = fetch_gid_csv(SHEET_ID, gids["USDINR"])
        except Exception as e: print(f"[warn] gid USDINR failed: {e}")
    if fx_df is None:
        try: fx_df = fetch_tab_csv(SHEET_ID, "USDINR")
        except Exception as e: print(f"[warn] USDINR tab fetch failed: {e}")
    have_fx = fx_df is not None and len(fx_df)>0
    fx = fx_df.set_index("date")["close"] if have_fx else pd.Series(dtype=float)
    if have_fx: print(f"[ok] USDINR rows={len(fx_df)}")
    else: print("[warn] No USDINR FX; INR positions will be treated as USD (mis-scaled)")

    if not all_dates: die("no quote data fetched (check Sheet mapping/permissions)")
    all_dates = pd.Index(sorted(list(all_dates)), dtype="object", name="date")

    def price_usd_on_date(symbol: str, price_local: float, on_date: str) -> float:
        cur = local_cur(symbol)
        if cur == "USD": return float(price_local)
        if cur == "INR" and have_fx:
            fxv = fx.reindex([on_date]).ffill().iloc[0]
            return float(price_local) / float(fxv)
        return float(price_local)

    # --- Compute qty from amount_usd if provided ---
    if "amount_usd" in tx.columns:
        need_qty = tx["qty"].isna() if "qty" in tx.columns else pd.Series(True, index=tx.index)
        for idx in tx[need_qty].index:
            sym = tx.at[idx, "symbol"]; d = tx.at[idx, "date"]
            pl  = float(tx.at[idx, "price_local"])
            pu  = price_usd_on_date(sym, pl, d)
            if pu and np.isfinite(pu) and pu > 0:
                tx.at[idx, "qty"] = float(tx.at[idx, "amount_usd"]) / pu
            else:
                die(f"Cannot convert amount_usd to qty for {sym} on {d} (missing FX or price).")
    tx["qty"] = pd.to_numeric(tx["qty"], errors="coerce").fillna(0.0)

    # --- Build holdings & invested (aligned by the same date index) ---
    holdings = {sym: pd.Series(0.0, index=all_dates) for sym in symbols}
    invested_usd = pd.Series(0.0, index=all_dates)
    for sym in symbols:
        h = pd.Series(0.0, index=all_dates)
        sym_tx = tx[tx["symbol"]==sym]
        for _,row in sym_tx.iterrows():
            q = float(row["qty"])
            d = row["date"]
            pl = float(row["price_local"])
            pu = price_usd_on_date(sym, pl, d)
            h.loc[h.index>=d] += q
            invested_usd.loc[invested_usd.index>=d] += q * pu
        holdings[sym] = h

    # --- Daily mark-to-market (USD) ---
    values_usd = pd.Series(0.0, index=all_dates, dtype=float)
    for sym in symbols:
        s = price_map[sym].set_index("date")["close"].reindex(all_dates).ffill().fillna(0.0)
        if local_cur(sym)=="INR" and have_fx:
            s = s / fx.reindex(all_dates).ffill().fillna(method="ffill")
        values_usd += s * holdings[sym]

    # --- Cash & NAV ---
    invested_usd = invested_usd.fillna(0.0)
    cash_usd = (STARTING_CASH - invested_usd).clip(lower=0.0)
    cash_usd = cash_usd.fillna(method='ffill').fillna(STARTING_CASH)
    nav_usd  = (values_usd + cash_usd).round(4)
    nav_usd  = nav_usd.fillna(cash_usd)

    # --- Inception & performance series ---
    invested_positive = invested_usd[invested_usd > 0]
    if len(invested_positive): inception = invested_positive.index.min()
    else:
        nz = nav_usd[nav_usd > 0]; inception = nz.index.min() if len(nz) else None

    if inception is None:
        nav_index = pd.Series(np.nan, index=all_dates)
        pnl_abs = pd.Series(np.nan, index=all_dates)
        pnl_pct = pd.Series(np.nan, index=all_dates)
    else:
        base_val = nav_usd.loc[inception]
        nav_index = (nav_usd / base_val * 100.0).round(4)
        pnl_abs   = (nav_usd - base_val).round(2)
        pnl_pct   = ((nav_usd / base_val - 1.0) * 100.0).round(3)

    # --- Write NAV files ---
    nav_df = pd.DataFrame({
        "nav_usd":      nav_usd,
        "cash_usd":     cash_usd.round(4),
        "holdings_usd": values_usd.round(4),
        "invested_usd": invested_usd.round(4),
        "nav_index":    nav_index,
        "pnl_abs_usd":  pnl_abs,
        "pnl_pct":      pnl_pct
    }, index=all_dates).reset_index(names="date")
    (DATA/"nav.json").write_text(nav_df.to_json(orient="records", force_ascii=False), encoding="utf-8")

    summary = {
        "base_currency":"USD","starting_cash":STARTING_CASH,
        "inception_date": inception if inception else None,
        "latest":{
            "date": str(all_dates[-1]),
            "nav": float(nav_usd.iloc[-1]),
            "cash": float(cash_usd.iloc[-1]),
            "holdings": float(values_usd.iloc[-1]),
            "invested": float(invested_usd.iloc[-1]),
            "pnl_abs": float(pnl_abs.iloc[-1]) if not pd.isna(pnl_abs.iloc[-1]) else None,
            "pnl_pct": float(pnl_pct.iloc[-1]) if not pd.isna(pnl_pct.iloc[-1]) else None
        }
    }
    (DATA/"nav_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- Write positions.json (authoritative for pages/table) ---
    pos_rows = []
    for sym in symbols:
        sym_tx = tx[tx["symbol"]==sym].sort_values("date")
        if sym_tx.empty: continue
        first = sym_tx.iloc[0]
        buy_date = first["date"]
        buy_price_local = float(first["price_local"])
        buy_price_usd = price_usd_on_date(sym, buy_price_local, buy_date)
        total_qty = float(sym_tx["qty"].sum())
        cost_local = total_qty * buy_price_local
        cost_usd   = total_qty * buy_price_usd
        pos_rows.append({
            "symbol": sym,
            "buy_date": buy_date,
            "buy_price_local": round(buy_price_local, 6),
            "buy_price_usd": round(buy_price_usd, 6),
            "qty": round(total_qty, 6),
            "cost_local": round(cost_local, 2),
            "cost_usd": round(cost_usd, 2)
        })
    (DATA/"positions.json").write_text(json.dumps(pos_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[done] quotes + NAV + positions generation complete")

if __name__=="__main__":
    main()
