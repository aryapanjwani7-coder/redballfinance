#!/usr/bin/env python3
"""
Red Ball Finance — data builder (INR).

One script, no API keys, stdlib only. For each holding (and the Nifty 50
benchmark) it fetches daily closes + dividends, then builds:

  data/quotes/<SYMBOL>.json   per-symbol price history  {date, close}
  data/quotes/NIFTY50.json    benchmark price history    {date, close}
  data/dividends.json         dividend events            {symbol, date, amount, amount_total_inr}
  data/positions.json         per-holding snapshot (qty, cost, value, P&L, dividends)
  data/nav.json               daily NAV series (INR) incl. nifty_index benchmark
  data/nav_summary.json       latest snapshot for the cards

Price source order (per symbol):
  1. Yahoo Finance chart API  (no key; gives prices AND dividends, INR native)
  2. Google Sheet tab          (gviz CSV fallback, if SHEET_ID is set)
  3. Existing data/quotes file (last-known cache, so a bad fetch never wipes data)

Everything is in INR. Both stocks trade on the NSE (.NS) so there is no FX.
"""
import os, sys, json, time, csv, datetime as dt
from pathlib import Path
from urllib.parse import quote
from io import StringIO
import urllib.request

# ================== CONFIG ==================
STARTING_CASH = float(os.getenv("STARTING_CASH", "10000000"))   # ₹1,00,00,000 (1 crore)
YEARS_BACK    = int(os.getenv("YEARS_BACK", "5"))
SHEET_ID      = os.getenv("SHEET_ID", "").strip()               # optional fallback only
BENCH_SYMBOL  = os.getenv("BENCH_SYMBOL", "^NSEI")              # Nifty 50
BENCH_FILE    = "NIFTY50"                                       # quotes/NIFTY50.json
# ============================================

ROOT   = Path(__file__).resolve().parents[2]
DATA   = ROOT / "data"
QUOTES = DATA / "quotes"
QUOTES.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def die(msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def http_get(url, tries=4, base_sleep=2.0):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept": "application/json,text/csv,*/*"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8")
        except Exception as e:
            last = e
            time.sleep(base_sleep * (i + 1))
    raise last


# ---------- source 1: Yahoo (direct, then via r.jina.ai proxy) ----------
def _yahoo_path(symbol):
    rng = "5y" if YEARS_BACK >= 5 else ("2y" if YEARS_BACK >= 2 else "1y")
    return (f"finance.yahoo.com/v8/finance/chart/{quote(symbol)}"
            f"?range={rng}&interval=1d&events=div")


def _extract_chart_json(txt):
    i = txt.find('{"chart"')
    if i < 0:
        i = txt.find('{')
    return json.loads(txt[i:]) if i >= 0 else None


def yahoo_chart(symbol):
    path = _yahoo_path(symbol)
    # 1) direct
    for host in ("query1", "query2"):
        try:
            js = json.loads(http_get(f"https://{host}.{path}", tries=2))
            if js.get("chart", {}).get("result"):
                print(f"[ok] yahoo direct {symbol}")
                return js
        except Exception as e:
            print(f"[warn] yahoo {host} {symbol}: {e}")
    # 2) via r.jina.ai proxy (works when the runner IP is rate-limited)
    for host in ("query1", "query2"):
        try:
            js = _extract_chart_json(http_get(f"https://r.jina.ai/https://{host}.{path}", tries=2))
            if js and js.get("chart", {}).get("result"):
                print(f"[ok] yahoo via proxy {symbol}")
                return js
        except Exception as e:
            print(f"[warn] yahoo proxy {host} {symbol}: {e}")
    return None


def parse_yahoo(js):
    res    = js["chart"]["result"][0]
    ts     = res.get("timestamp", []) or []
    closes = (res.get("indicators", {}).get("quote", [{}])[0] or {}).get("close", [])
    by_date = {}
    for t, c in zip(ts, closes):
        if c is None:
            continue
        d = dt.datetime.utcfromtimestamp(t).date().isoformat()
        by_date[d] = round(float(c), 4)
    prices = [{"date": d, "close": by_date[d]} for d in sorted(by_date)]
    divs = []
    for v in (res.get("events", {}).get("dividends", {}) or {}).values():
        try:
            d = dt.datetime.utcfromtimestamp(int(v["date"])).date().isoformat()
            divs.append({"date": d, "amount": round(float(v["amount"]), 4)})
        except Exception:
            continue
    divs.sort(key=lambda x: x["date"])
    return prices, divs


# ---------- source 2: Google Sheet ----------
def sheet_prices(symbol):
    if not SHEET_ID:
        return []
    tab = symbol.upper().replace(".", "_")
    url = (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq"
           f"?tqx=out:csv&sheet={quote(tab)}")
    try:
        txt = http_get(url, tries=2)
    except Exception as e:
        print(f"[warn] sheet {symbol}: {e}")
        return []
    out = {}
    for i, row in enumerate(csv.reader(StringIO(txt))):
        if i == 0 or len(row) < 2:
            continue
        d = parse_date(row[0])
        try:
            c = float(str(row[1]).replace(",", ""))
        except Exception:
            continue
        if d:
            out[d] = round(c, 4)
    return [{"date": d, "close": out[d]} for d in sorted(out)]


def parse_date(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%d-%b-%Y", "%b %d, %Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# ---------- source 3: cached file ----------
def cached_prices(fname):
    p = QUOTES / f"{fname}.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def get_prices_and_divs(symbol, fname):
    """Return (prices, dividends). Dividends only come from Yahoo."""
    js = yahoo_chart(symbol)
    if js:
        prices, divs = parse_yahoo(js)
        if prices:
            print(f"[ok] yahoo {symbol}: {len(prices)} rows, {len(divs)} dividends")
            return prices, divs
    sp = sheet_prices(symbol)
    if sp:
        print(f"[ok] sheet {symbol}: {len(sp)} rows (no dividends from sheet)")
        return sp, None
    cp = cached_prices(fname)
    print(f"[warn] {symbol}: using cached {fname}.json ({len(cp)} rows)")
    return cp, None


# ---------- helpers ----------
def ffill_on(axis, series):
    """series: {date: value}; return {date: value} forward-filled across axis."""
    out, last = {}, None
    for d in axis:
        if d in series:
            last = series[d]
        out[d] = last
    return out


def write_json(path, obj, indent=None):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=indent), encoding="utf-8")


def main():
    print(f"[info] BASE=INR  STARTING_CASH={STARTING_CASH:,.0f}  YEARS_BACK={YEARS_BACK}")

    tx_path = DATA / "transactions.json"
    if not tx_path.exists():
        die("data/transactions.json not found")
    tx = json.loads(tx_path.read_text(encoding="utf-8"))
    for t in tx:
        for k in ("symbol", "date", "price_local"):
            if k not in t:
                die(f"transaction missing '{k}': {t}")
        t["qty"] = float(t["amount_inr"]) / float(t["price_local"]) \
            if t.get("amount_inr") else float(t.get("qty", 0))
    symbols = sorted({t["symbol"] for t in tx})

    # --- fetch holdings ---
    price_map, div_map = {}, {}
    for sym in symbols:
        prices, divs = get_prices_and_divs(sym, sym)
        write_json(QUOTES / f"{sym}.json", prices)
        price_map[sym] = {r["date"]: r["close"] for r in prices}
        if divs is not None:
            div_map[sym] = divs

    # --- benchmark (Nifty 50) ---
    bench_prices, _ = get_prices_and_divs(BENCH_SYMBOL, BENCH_FILE)
    write_json(QUOTES / f"{BENCH_FILE}.json", bench_prices)
    bench_series = {r["date"]: r["close"] for r in bench_prices}

    # --- dividends.json (keep cache if no fresh data fetched) ---
    if div_map:
        rows = []
        qty_by_sym = {s: sum(t["qty"] for t in tx if t["symbol"] == s) for s in symbols}
        buy_by_sym = {s: min(t["date"] for t in tx if t["symbol"] == s) for s in symbols}
        for sym, divs in div_map.items():
            for d in divs:
                if d["date"] < buy_by_sym[sym]:
                    continue  # only count dividends after we owned it
                rows.append({
                    "symbol": sym,
                    "date": d["date"],
                    "amount": d["amount"],
                    "amount_total_inr": round(d["amount"] * qty_by_sym[sym], 2),
                })
        rows.sort(key=lambda r: (r["date"], r["symbol"]))
        write_json(DATA / "dividends.json", rows)
        dividends = rows
    else:
        try:
            dividends = json.loads((DATA / "dividends.json").read_text(encoding="utf-8"))
        except Exception:
            dividends = []
        print("[warn] no fresh dividends fetched; kept existing dividends.json")

    # --- date axis = union of holding trading days ---
    axis = sorted({d for sym in symbols for d in price_map[sym]})
    if not axis:
        die("no price data for any holding")

    ff = {sym: ffill_on(axis, price_map[sym]) for sym in symbols}
    bench_ff = ffill_on(axis, bench_series)

    inception = min(t["date"] for t in tx)
    div_by_date = {}
    for d in dividends:
        div_by_date[d["date"]] = div_by_date.get(d["date"], 0.0) + d["amount_total_inr"]

    # --- daily series ---
    nav_rows = []
    div_cum = 0.0
    base_nav = None
    base_bench = None
    for d in axis:
        if d in div_by_date:
            div_cum += div_by_date[d]
        holdings = 0.0
        invested = 0.0
        for t in tx:
            if d >= t["date"]:
                px = ff[t["symbol"]].get(d)
                if px:
                    holdings += t["qty"] * px
                invested += float(t.get("amount_inr", t["qty"] * t["price_local"]))
        cash = max(0.0, STARTING_CASH - invested) + div_cum
        nav = holdings + cash
        if d >= inception and base_nav is None:
            base_nav = nav
            base_bench = bench_ff.get(d)
        nav_rows.append({
            "date": d,
            "nav_inr": round(nav, 4),
            "cash_inr": round(cash, 4),
            "holdings_inr": round(holdings, 4),
            "invested_inr": round(invested, 4),
            "dividends_inr": round(div_cum, 4),
            "_bench": bench_ff.get(d),
        })

    for r in nav_rows:
        r["nav_index"] = round(r["nav_inr"] / base_nav * 100.0, 4) if base_nav else None
        r["pnl_abs_inr"] = round(r["nav_inr"] - base_nav, 2) if base_nav else None
        r["pnl_pct"] = round((r["nav_inr"] / base_nav - 1.0) * 100.0, 3) if base_nav else None
        b = r.pop("_bench")
        r["nifty_index"] = round(b / base_bench * 100.0, 4) if (b and base_bench) else None

    write_json(DATA / "nav.json", nav_rows)

    # --- positions.json (everything the table needs, precomputed) ---
    last_date = axis[-1]
    positions = []
    for sym in symbols:
        sym_tx = sorted([t for t in tx if t["symbol"] == sym], key=lambda t: t["date"])
        first = sym_tx[0]
        qty = sum(t["qty"] for t in sym_tx)
        cost = sum(float(t.get("amount_inr", t["qty"] * t["price_local"])) for t in sym_tx)
        last_px = ff[sym].get(last_date) or first["price_local"]
        mkt = qty * last_px
        sym_div = round(sum(d["amount_total_inr"] for d in dividends if d["symbol"] == sym), 2)
        total_ret = mkt + sym_div - cost
        positions.append({
            "symbol": sym,
            "buy_date": first["date"],
            "buy_price_local": round(float(first["price_local"]), 4),
            "qty": round(qty, 4),
            "cost_local": round(cost, 2),
            "last_price": round(last_px, 4),
            "last_date": last_date,
            "market_value_local": round(mkt, 2),
            "dividends_local": sym_div,
            "pnl_local": round(total_ret, 2),
            "pnl_pct": round(total_ret / cost * 100.0, 3) if cost else None,
        })
    write_json(DATA / "positions.json", positions, indent=2)

    # --- summary ---
    latest = nav_rows[-1]
    bench_pnl = None
    if latest.get("nifty_index") is not None:
        bench_pnl = round(latest["nifty_index"] - 100.0, 3)
    summary = {
        "base_currency": "INR",
        "starting_cash": STARTING_CASH,
        "inception_date": inception,
        "latest": {
            "date": latest["date"],
            "nav": latest["nav_inr"],
            "cash": latest["cash_inr"],
            "holdings": latest["holdings_inr"],
            "invested": latest["invested_inr"],
            "dividends": latest["dividends_inr"],
            "pnl_abs": latest["pnl_abs_inr"],
            "pnl_pct": latest["pnl_pct"],
            "nifty_pnl_pct": bench_pnl,
        },
    }
    write_json(DATA / "nav_summary.json", summary, indent=2)

    print(f"[done] inception={inception} last={last_date} "
          f"nav={latest['nav_inr']:,.0f} pnl%={latest['pnl_pct']} "
          f"nifty%={bench_pnl} dividends={latest['dividends_inr']:,.0f}")


if __name__ == "__main__":
    main()
